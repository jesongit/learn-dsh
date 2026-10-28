"""M2-01 测试：SSE 解析 / 事件翻译 / 端到端流（不联网——MockTransport 回放预录 SSE）。

测试即规格：读断言 = 读 DeepSeekAdapter 的契约。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from pagent.deepseek import SSE_SAMPLE, DeepSeekAdapter
from pagent.types import (
    Finish,
    GenerateOptions,
    Message,
    StreamChunk,
    TextBlock,
    TextDelta,
    ToolCallDelta,
)


def test_parse_sse_extracts_five_events():
    """契约：逐行剥壳，[DONE] 是终结符不算事件。"""
    events = DeepSeekAdapter.parse_sse(SSE_SAMPLE)
    assert len(events) == 5
    assert events[0]["choices"][0]["delta"]["content"] == "你"
    assert events[2]["choices"][0]["delta"]["tool_calls"][0]["id"] == "call-1"
    assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_translate_text_and_finish():
    """契约：文本增量与结束原因的一对一映射。"""
    text_event = {"choices": [{"delta": {"content": "你"}}]}
    finish_event = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    assert DeepSeekAdapter.translate_event(text_event) == [TextDelta(index=0, text="你")]
    assert DeepSeekAdapter.translate_event(finish_event) == [Finish(reason="tool-calls")]


def test_translate_tool_call_split_frames():
    """契约：参数分片帧——id/name 只在首帧，两片拼回完整 JSON。"""
    first = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call-1", "function": {"name": "echo", "arguments": '{"text": '}}]}}]}
    second = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": '"hi"}'}}]}}]}
    chunks = (
        DeepSeekAdapter.translate_event(first)
        + DeepSeekAdapter.translate_event(second)
    )
    assert all(isinstance(c, ToolCallDelta) for c in chunks)
    assert chunks[0].id == "call-1" and chunks[0].name == "echo"
    assert chunks[1].name is None                       # 身份只说一次
    assert chunks[0].arguments_delta + chunks[1].arguments_delta == '{"text": "hi"}'


def test_stream_end_to_end_without_network():
    """契约：串装——请求带 stream=true 且消息形状正确；响应逐帧成 chunk。"""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, text=SSE_SAMPLE)

    adapter = DeepSeekAdapter(api_key="test", transport=httpx.MockTransport(handler))
    options = GenerateOptions(
        model="deepseek-chat",
        messages=[Message(role="user", content=[TextBlock(text="你好")])],
    )

    async def run() -> list[StreamChunk]:
        return [chunk async for chunk in adapter.stream(options)]

    chunks = asyncio.run(run())

    # 请求侧：流式开关与消息形状（你的 _build_body 的产出）
    assert captured[0]["stream"] is True
    assert captured[0]["model"] == "deepseek-chat"
    assert captured[0]["messages"] == [{"role": "user", "content": "你好"}]

    # 响应侧：顺序与内容
    assert [type(c).__name__ for c in chunks] == [
        "TextDelta", "TextDelta", "ToolCallDelta", "ToolCallDelta", "Finish",
    ]
    tool = [c for c in chunks if isinstance(c, ToolCallDelta)]
    assert tool[0].arguments_delta + tool[1].arguments_delta == '{"text": "hi"}'
    assert chunks[-1] == Finish(reason="tool-calls")
