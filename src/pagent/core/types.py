"""消息与流式词汇表 —— PAgent 的「通用语言」。

对照：deepseek-harness@53d1ef4a74 packages/llm/src/types.ts
（provider-neutral message & streaming vocabulary）。

这是 agent loop、会话日志、工具管线共用的唯一词汇。真实模型的
wire format（比如 DeepSeek 的 HTTP JSON 结构）只允许出现在
adapter 内部——本文件里的类型对任何模型都成立。

v0 简化（相对 harness）：
- 只有 text / tool-call / tool-result 三种内容块（reasoning / image 留待扩展）
- finish reason 用字符串字面量而非可合并的 map（Python 没有 TS 的
  declaration merging，扩展就加字面量）
- 流式 chunk 只保留 v0 必需的六种
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

Role = Literal["system", "user", "assistant"]
FinishReason = Literal["stop", "tool-calls", "max-tokens", "aborted"]


# ---------- 内容块：一条消息由若干内容块组成 ----------


@dataclass(frozen=True)
class ContentBlock:
    """所有内容块的基类；具体类型用 isinstance 区分。"""

    type: ClassVar[str]


@dataclass(frozen=True)
class TextBlock(ContentBlock):
    """给用户看的普通文本。"""

    type: ClassVar[str] = "text"
    text: str


@dataclass(frozen=True)
class ToolCallBlock(ContentBlock):
    """模型请求的一次工具调用。

    id 由「模型」签发，用于与对应的 ToolResultBlock 配对；
    arguments 是模型产出的原始 JSON 字符串（解析交给执行方）。
    """

    type: ClassVar[str] = "tool-call"
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolResultBlock(ContentBlock):
    """工具执行结果，用 tool_call_id 与调用配对后回填进消息历史。"""

    type: ClassVar[str] = "tool-result"
    tool_call_id: str
    content: list[ContentBlock]
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    """对话历史里的一条消息。"""

    role: Role
    content: list[ContentBlock]


@dataclass(frozen=True)
class ToolSchema:
    """发给模型的工具说明书：名字、描述、参数的 JSON Schema。"""

    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class TokenUsage:
    """一次模型调用的 token 记账（M4 压缩策略的原料）。"""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class GenerateOptions:
    """一次完整的模型请求（组装好的，不可变）。"""

    model: str
    messages: list[Message]
    system: str | None = None
    tools: list[ToolSchema] | None = None


# ---------- 流式 chunk：adapter 输出的原始流 ----------


@dataclass(frozen=True)
class BlockStart:
    """一个内容块开始；index 把后续 delta 绑定到这个块。"""

    index: int
    block_type: str  # ContentBlock.type 之一


@dataclass(frozen=True)
class TextDelta:
    """文本增量。"""

    index: int
    text: str


@dataclass(frozen=True)
class ToolCallDelta:
    """工具调用参数的增量——模型流式地吐 JSON 参数片。"""

    index: int
    id: str
    name: str | None
    arguments_delta: str


@dataclass(frozen=True)
class BlockEnd:
    """一个内容块组装完毕，携带完整块（消费方不必自己拼增量）。"""

    index: int
    block: ContentBlock


@dataclass(frozen=True)
class UsageChunk:
    """本流的 token 记账。"""

    usage: TokenUsage


@dataclass(frozen=True)
class Finish:
    """流结束及原因。"""

    reason: FinishReason


StreamChunk = BlockStart | TextDelta | ToolCallDelta | BlockEnd | UsageChunk | Finish
