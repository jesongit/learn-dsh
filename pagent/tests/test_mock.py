"""M1-01 测试：示例已通过；三个 TODO 是你的任务。

运行：uv run pytest tests/test_mock.py -v
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


def collect(chunks: list[StreamChunk]) -> str:
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
    """TODO(1)：验证 tool_call_response。

    构造 tool_call_response("call-1", "echo", {"text": "hi"})，断言：
    - 出现一个 BlockStart 且 block_type == "tool-call"
    - 出现两个 ToolCallDelta，两者 arguments_delta 拼起来
      等于 json.dumps({"text": "hi"})；第一个的 name == "echo"
    - 出现一个 BlockEnd，其 block 是 ToolCallBlock：
      id == "call-1"，arguments 反序列化后 == {"text": "hi"}
    - 最后一个 chunk 是 Finish 且 reason == "tool-calls"
    """
    raise NotImplementedError("删掉这行，写你的断言")


def _drain(chunks: list[StreamChunk]) -> list[StreamChunk]:
    """把 adapter 的流跑完，收集所有 chunk（asyncio.run 包同步测试）。"""

    async def _run() -> list[StreamChunk]:
        adapter = MockAdapter(chunks)
        options = GenerateOptions(model="mock", messages=[])
        return [chunk async for chunk in adapter.stream(options)]

    return asyncio.run(_run())


def test_mock_adapter_streams_script_and_records_requests():
    """TODO(2)：MockAdapter 按脚本出牌并记录请求。

    - _drain(text_response("a")) 返回的 chunk 列表应与脚本一致
    - 证明请求被记录：直接 new 一个 MockAdapter，手动调一次 stream()
      （asyncio.run 包住，异步 for 消费），断言 adapter.requests 里
      存的正是你发的那个 GenerateOptions 对象
    """
    raise NotImplementedError("删掉这行，写你的断言")


def test_mock_adapter_raises_when_script_exhausted():
    """TODO(3)：脚本耗尽后再取应抛 RuntimeError("MockAdapter: 脚本耗尽")。

    提示：pytest.raises(RuntimeError, match="脚本耗尽")；
    第一次 stream 把唯一脚本消费掉，第二次再 stream 应抛错。
    """
    raise NotImplementedError("删掉这行，写你的断言")
