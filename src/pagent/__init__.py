"""PAgent —— 通过复刻 DeepSeek Harness 学出来的 Python Agent。

M1：词汇表 + adapter 接缝 + mock 模型 + 会话日志 + agent loop。
"""

from pagent.llm.adapter import LLMAdapter, LlmService
from pagent.core.agent import Agent
from pagent.core.assembler import BlockAssembler
from pagent.core.inbox import Inbox, InboxMessage
from pagent.core.session import Session, SessionEvent
from pagent.tools.registry import ToolOutcome, ToolService
from pagent.core.types import (
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
    "Agent",
    "BlockAssembler",
    "BlockEnd",
    "BlockStart",
    "Finish",
    "GenerateOptions",
    "Inbox",
    "InboxMessage",
    "LLMAdapter",
    "LlmService",
    "Message",
    "Session",
    "SessionEvent",
    "StreamChunk",
    "TextBlock",
    "TextDelta",
    "TokenUsage",
    "ToolCallBlock",
    "ToolCallDelta",
    "ToolOutcome",
    "ToolResultBlock",
    "ToolSchema",
    "ToolService",
    "UsageChunk",
]
