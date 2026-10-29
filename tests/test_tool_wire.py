"""M3-03 作业区：工具 wire format · 请求方向（测试即规格）。

TODO(E)(F) 骨架在 src/pagent/deepseek.py 的 _build_body 注释区；用例 skip
挂起，实现一条解锁一条（建议 E → F）。test_plain_messages_unchanged 不挂
skip——它是回归护栏，锁住 M2-01 的纯文本行为不被重构破坏。
运行：uv run pytest tests/test_tool_wire.py -v
"""

from __future__ import annotations

import pytest

from pagent.deepseek import DeepSeekAdapter
from pagent.types import (
    GenerateOptions,
    Message,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolSchema,
)

ADAPTER = DeepSeekAdapter("fake-key")


def test_plain_messages_unchanged():
    """回归护栏：纯文本消息的翻译与 M2-01 完全一致（重构不得破坏）。"""
    options = GenerateOptions(
        model="deepseek-chat",
        messages=[Message(role="user", content=[TextBlock(text="你好")])],
        system="你是 PAgent",
    )
    body = ADAPTER._build_body(options)
    assert body["messages"] == [
        {"role": "system", "content": "你是 PAgent"},
        {"role": "user", "content": "你好"},
    ]
    assert "tools" not in body  # 没工具就不该有 tools 键



def test_body_carries_tool_schemas():
    """契约：tools 非空 → 说明书以 function-calling 形状随请求发出。"""
    options = GenerateOptions(
        model="deepseek-chat",
        messages=[],
        tools=[ToolSchema(name="bash_run", description="执行命令",
                          parameters={"type": "object"})],
    )
    body = ADAPTER._build_body(options)
    assert body["tools"] == [{
        "type": "function",
        "function": {"name": "bash_run", "description": "执行命令",
                     "parameters": {"type": "object"}},
    }]



def test_assistant_tool_calls_array():
    """契约：assistant 的 ToolCallBlock → tool_calls 数组（content 允许空串）。

    断言拆小：大结构单断言的失败 diff 会被 pytest 截断到读不了——
    先量条数、再逐键比，每次失败都直指具体形状差在哪。
    """
    options = GenerateOptions(
        model="deepseek-chat",
        messages=[Message(role="assistant",
                          content=[ToolCallBlock(id="c1", name="bash_run",
                                                 arguments='{"command": "ls"}')])],
    )
    body = ADAPTER._build_body(options)
    msgs = body["messages"]
    assert len(msgs) == 1, f"应产出 1 条 wire 消息，实得 {len(msgs)} 条：{msgs!r}"
    msg = msgs[0]
    assert msg["role"] == "assistant", f"role 错：{msg.get('role')!r}"
    assert msg["content"] == "", f"content 应为空串：{msg.get('content')!r}"
    assert msg["tool_calls"] == [{
        "id": "c1", "type": "function",
        "function": {"name": "bash_run", "arguments": '{"command": "ls"}'},
    }], f"tool_calls 形状错：{msg.get('tool_calls')!r}"


def test_tool_result_becomes_role_tool():
    """契约：user 的 ToolResultBlock → 独立 role:"tool" 消息，id 原样回传。

    tool_call_id 是模型的对账凭据（M3-03 教材）；content 取结果内 Text 拼接。
    """
    options = GenerateOptions(
        model="deepseek-chat",
        messages=[Message(role="user",
                          content=[ToolResultBlock(tool_call_id="c1",
                                                   content=[TextBlock(text="hi\n")],
                                                   is_error=False)])],
    )
    body = ADAPTER._build_body(options)
    msgs = body["messages"]
    assert len(msgs) == 1, f"应产出 1 条 wire 消息，实得 {len(msgs)} 条：{msgs!r}"
    assert msgs[0] == {"role": "tool", "tool_call_id": "c1", "content": "hi\n"}, \
        f"wire 消息形状错：{msgs!r}"
