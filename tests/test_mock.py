"""M1-01 测试 —— 测试是行为规格：读断言就是在读 MockAdapter 的契约。

实现（mock.py）由用户亲手写；3 个 TODO 断言按用户要求由 AI 以
「参考实现」补全（另加 1 个回归测试）。M1-02/03 的场景测试仍须用户亲手写。

运行：uv run pytest -v
"""

from __future__ import annotations

import asyncio
import json

import pytest

from pagent.mock import MockAdapter, text_response, tool_call_response
from pagent.types import (
    BlockEnd,
    BlockStart,
    Finish,
    GenerateOptions,
    StreamChunk,
    TextDelta,
    ToolCallBlock,
    ToolCallDelta,
)


def collect_text(chunks: list[StreamChunk]) -> str:
    """把一段脚本里的所有 TextDelta 拼回原文本（后面章节还会用到）。"""
    return "".join(c.text for c in chunks if isinstance(c, TextDelta))


def test_text_response_is_a_worked_example():
    """示例测试（已写好）：验证 text_response 的固定节奏。"""
    chunks = text_response("hi")
    assert isinstance(chunks[0], BlockStart) and chunks[0].index == 0
    assert chunks[1:-3] == [TextDelta(index=0, text="h"), TextDelta(index=0, text="i")]
    assert isinstance(chunks[-3], BlockEnd) and chunks[-3].block.text == "hi"
    assert isinstance(chunks[-1], Finish) and chunks[-1].reason == "stop"


def test_tool_call_response_shape():
    """契约：一次工具调用响应 = 工具块（两片参数增量）+ 记账 + 宣终。"""
    chunks = tool_call_response("call-1", "echo", {"text": "hi"})

    # 没给 text：整条响应只应有一个块，由一个 tool-call 的 BlockStart 开路
    starts = [c for c in chunks if isinstance(c, BlockStart)]
    assert [s.block_type for s in starts] == ["tool-call"]

    # 两片参数增量：第一片带名字，第二片 name=None（身份只说一次）；
    # 同一 id、同一 index；两片拼起来等于完整 JSON
    deltas = [c for c in chunks if isinstance(c, ToolCallDelta)]
    assert [d.name for d in deltas] == ["echo", None]
    assert all(d.id == "call-1" and d.index == starts[0].index for d in deltas)
    assert deltas[0].arguments_delta + deltas[1].arguments_delta == json.dumps({"text": "hi"})

    # BlockEnd 携带完整块——不想拼增量的消费方拿它就行
    ends = [c for c in chunks if isinstance(c, BlockEnd)]
    assert len(ends) == 1
    block = ends[0].block
    assert isinstance(block, ToolCallBlock)
    assert block.id == "call-1" and block.name == "echo"
    assert json.loads(block.arguments) == {"text": "hi"}

    # 结尾是 tool-calls 而非 stop——下一节 loop 的方向盘
    assert chunks[-1] == Finish(reason="tool-calls")


def test_tool_call_response_with_text_prefix():
    """回归测试：text 非空时文本块 index=0 在前、工具块 index=1 在后。

    （这曾是实现里的真 bug：`text_response[:-2]` 切了函数对象而非返回值。）
    """
    chunks = tool_call_response("call-1", "echo", {"text": "hi"}, text="我来查一下")
    assert isinstance(chunks[0], BlockStart) and chunks[0].block_type == "text"
    assert chunks[0].index == 0
    tool_start = next(
        c for c in chunks if isinstance(c, BlockStart) and c.block_type == "tool-call"
    )
    assert tool_start.index == 1
    assert collect_text(chunks) == "我来查一下"
    assert chunks[-1] == Finish(reason="tool-calls")


def test_mock_adapter_streams_script_and_records_requests():
    """契约：stream 按剧本逐 chunk 出牌；requests 记账；消费后剧本清空。"""
    # stream 逐个 yield 的 chunk 应与剧本一致（dataclass 逐个相等）
    assert _drain(text_response("a")) == text_response("a")

    async def _run_and_capture():
        adapter = MockAdapter([text_response("a")])
        options = GenerateOptions(model="mock", messages=[])
        async for _ in adapter.stream(options):
            pass
        return adapter

    adapter = asyncio.run(_run_and_capture())
    assert len(adapter.requests) == 1            # 每次请求都记账
    assert adapter.requests[0].model == "mock"   # 记的是请求本身
    assert adapter.script == []                  # 消费过的响应从剧本里取走


def test_mock_adapter_raises_when_script_exhausted():
    """契约：剧本耗尽后，下一次流式迭代抛 RuntimeError。

    Python 陷阱：async generator 调用时一行都不执行，迭代才执行——
    所以必须在 async for 里等它炸，光调用 stream() 什么都不会发生。
    """
    async def _run():
        adapter = MockAdapter([text_response("a")])
        options = GenerateOptions(model="mock", messages=[])
        async for _ in adapter.stream(options):
            pass
        with pytest.raises(RuntimeError, match="脚本耗尽"):
            async for _ in adapter.stream(options):
                pass

    asyncio.run(_run())


def _drain(chunks: list[StreamChunk]) -> list[StreamChunk]:
    """把 adapter 的流跑完，收集所有 chunk（asyncio.run 包同步测试）。"""

    async def _run() -> list[StreamChunk]:
        adapter = MockAdapter([chunks])  # 剧本 = [一条完整响应]
        options = GenerateOptions(model="mock", messages=[])
        return [chunk async for chunk in adapter.stream(options)]

    return asyncio.run(_run())
