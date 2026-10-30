"""M4-02 作业区：压缩——哨兵事件 + 投影重建（测试即规格）。

TODO(O) 在 src/pagent/session.py（derive_messages 哨兵规则）、TODO(P) 同文件
（compact 方法）、TODO(Q) 在 src/pagent/loop.py（触发判定）——三条 skip 挂起，
按 O → P → Q 逐条解锁（删对应 skip），全绿 = 本节完成。
"""

from __future__ import annotations

import asyncio

import pytest

from pagent.adapter import LlmService
from pagent.agent import Agent
from pagent.loop import run_until_idle
from pagent.mock import MockAdapter, text_response, tool_call_response
from pagent.session import Session
from pagent.tools import ToolService
from pagent.types import Message, TextBlock


@pytest.mark.skip(reason="TODO(O) 实现后删除本行")
def test_projection_rebuilds_after_compaction():
    """契约：遇 compaction/end 哨兵 → 此前历史整体替换为摘要消息，之后照旧累积。"""
    session = Session("test-projection")
    session.append("user/message", {"content": [TextBlock(text="第一轮问题")]})
    session.append("assistant/message", {"content": [TextBlock(text="第一轮回答")]})
    session.append("compaction/end", {"upto_seq": 1, "summary": "旧叙事摘要"})
    session.append("user/message", {"content": [TextBlock(text="压缩后的问题")]})

    messages = session.derive_messages()
    assert len(messages) == 2, f"压缩后投影应只有摘要+哨兵后的消息：{messages!r}"
    assert messages[0].role == "user"
    assert "<compacted>旧叙事摘要</compacted>" in messages[0].content[0].text
    assert messages[1] == Message(role="user", content=[TextBlock(text="压缩后的问题")])


@pytest.mark.skip(reason="TODO(P) 实现后删除本行")
def test_compact_appends_sentinel_with_stub_summary():
    """契约：compact 截至某 seq 的叙事 → 落 compaction/end 哨兵，data 含摘要。"""
    session = Session("test-compact")
    session.append("user/message", {"content": [TextBlock(text="帮我查一下天气好吗")]})
    session.append("assistant/message", {"content": [TextBlock(text="好的我来调用工具")]})

    event = session.compact(upto_seq=1)

    assert event.type == "compaction/end"
    assert event.data["upto_seq"] == 1
    summary = event.data["summary"]
    assert "查一下天气" in summary  # v0 stub：旧叙事截断拼接
    assert "调用工具" in summary


@pytest.mark.skip(reason="TODO(Q) 实现后删除本行")
def test_loop_triggers_compaction_on_budget():
    """契约：最近 usage 的 input 逼近预算 → loop 自动压缩。

    场景：max_input_tokens=10，step 1 工具调用（usage input=10 ≥ 阈值）→
    step 2 组装前触发压缩。断言：哨兵落日志、其后投影变短。
    """
    session = Session("test-trigger")
    llm = LlmService()
    adapter = MockAdapter([
        tool_call_response("c1", "echo", {}),  # step 1：(input=10)
        text_response("done"),                  # step 2
    ])
    llm.register(["mock"], adapter)
    agent = Agent(id="a1", session=session, llm=llm,
                  tools=ToolService(), model="mock", max_input_tokens=10)
    agent.send([TextBlock(text="跑起来")])

    asyncio.run(run_until_idle(agent))

    compactions = [e for e in session.events if e.type == "compaction/end"]
    assert len(compactions) == 1, f"应恰好触发一次压缩：{len(compactions)}"
    # 压缩后的投影：第一条是摘要信封，其后是哨兵之后的 assistant 回复；
    # 原始叙事不再逐条出现（v0 stub 摘要里含原文片段，属预期）
    projected = session.derive_messages()
    assert len(projected) == 2, f"投影应收缩为 摘要+哨兵后消息：{projected!r}"
    assert projected[0].content[0].text.startswith("<compacted>")
    assert "done" in projected[1].content[0].text  # 哨兵之后的内容照常累积


@pytest.mark.skip(reason="TODO(Q) 实现后删除本行")
def test_no_compaction_without_budget():
    """回归护栏：未设预算（None）时永不压缩。"""
    session = Session("test-nobudget")
    llm = LlmService()
    adapter = MockAdapter([text_response("hi")])
    llm.register(["mock"], adapter)
    agent = Agent(id="a1", session=session, llm=llm,
                  tools=ToolService(), model="mock")
    agent.send([TextBlock(text="跑")])

    asyncio.run(run_until_idle(agent))

    assert [e for e in session.events if e.type == "compaction/end"] == []
