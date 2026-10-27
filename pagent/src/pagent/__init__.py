"""PAgent —— 通过复刻 DeepSeek Harness 学出来的 Python Agent。

M1-01 起步：消息/流式词汇表 + LLM 适配器接缝 + Mock 适配器。
"""

from pagent.adapter import LLMAdapter, LlmService
from pagent.types import (
    BlockEnd,
    BlockStart,
    Finish,
    GenerateOptions,
    Message,
    StreamChunk,
    TextBlock,
    TextDelta,
    TokenUsage,
    ToolCallBlock,
    ToolCallDelta,
    ToolResultBlock,
    ToolSchema,
    UsageChunk,
)

__all__ = [
    "BlockEnd",
    "BlockStart",
    "Finish",
    "GenerateOptions",
    "LLMAdapter",
    "LlmService",
    "Message",
    "StreamChunk",
    "TextBlock",
    "TextDelta",
    "TokenUsage",
    "ToolCallBlock",
    "ToolCallDelta",
    "ToolResultBlock",
    "ToolSchema",
    "UsageChunk",
]
