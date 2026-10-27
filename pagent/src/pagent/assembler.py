"""BlockAssembler：把 chunk 增量流拼回完整内容块与最终 assistant 消息。

对照：deepseek-harness@53d1ef4a74 packages/llm/src/assembler.ts。

消费 chunk 的两条路（都合法）：
- 懒路：只在 BlockEnd 取完整块（增量白流，省事）；
- 勤路：自己按增量拼（M2 的 UI 逐字渲染只能走这条）。
本组装器两条都支持：BlockEnd 给的块优先，没给就按增量拼。
"""

from __future__ import annotations

from dataclasses import dataclass

from pagent.types import (
    BlockEnd,
    BlockStart,
    ContentBlock,
    Finish,
    FinishReason,
    Message,
    StreamChunk,
    TextBlock,
    TokenUsage,
    ToolCallBlock,
    ToolCallDelta,
    UsageChunk,
)


@dataclass
class _Partial:
    """一个尚未收块的中间状态（按 index 对号）。"""

    block_type: str
    text: str = ""
    tool_call_id: str | None = None
    tool_call_name: str | None = None
    tool_call_arguments: str = ""
    block: ContentBlock | None = None


class BlockAssembler:
    def __init__(self) -> None:
        self._partials: dict[int, _Partial] = {}
        self._order: list[int] = []  # 按流中出现顺序输出
        self._usage: TokenUsage | None = None
        self._finish: FinishReason | None = None

    def push(self, chunk: StreamChunk) -> ContentBlock | None:
        """喂一个 chunk；chunk 收掉一个块时返回它，否则返回 None。"""
        if isinstance(chunk, BlockStart):
            if chunk.index not in self._partials:
                self._order.append(chunk.index)
            self._partials[chunk.index] = _Partial(block_type=chunk.block_type)
            return None
        if isinstance(chunk, TextDelta):
            partial = self._ensure(chunk.index, "text")
            partial.text += chunk.text
            return None
        if isinstance(chunk, ToolCallDelta):
            partial = self._ensure(chunk.index, "tool-call")
            partial.tool_call_id = chunk.id
            # 身份只说一次：有新名字才更新（M1-01 讲过的协议约定）
            if chunk.name:
                partial.tool_call_name = chunk.name
            partial.tool_call_arguments += chunk.arguments_delta
            return None
        if isinstance(chunk, BlockEnd):
            partial = self._ensure(chunk.index, chunk.block.type)
            partial.block = chunk.block
            return chunk.block
        if isinstance(chunk, UsageChunk):
            self._usage = chunk.usage
            return None
        if isinstance(chunk, Finish):
            self._finish = chunk.reason
            return None
        raise TypeError(f"未知 chunk 类型: {type(chunk).__name__}")

    def _ensure(self, index: int, block_type: str) -> _Partial:
        """容错：没见过 BlockStart 也能从中间开始拼（对照 TS 的 ensure）。"""
        partial = self._partials.get(index)
        if partial is None:
            partial = _Partial(block_type=block_type)
            self._partials[index] = partial
            self._order.append(index)
        return partial

    def blocks(self) -> list[ContentBlock]:
        """按流中出现顺序输出所有已见块。"""
        out: list[ContentBlock] = []
        for index in self._order:
            partial = self._partials[index]
            if partial.block is not None:
                out.append(partial.block)
                continue
            if partial.block_type == "text":
                out.append(TextBlock(text=partial.text))
            elif partial.block_type == "tool-call":
                out.append(
                    ToolCallBlock(
                        id=partial.tool_call_id or f"call-{index}",
                        name=partial.tool_call_name or "",
                        arguments=partial.tool_call_arguments,
                    )
                )
            else:
                raise ValueError(f"无法组装未完成的块类型 {partial.block_type!r}")
        return out

    @property
    def usage(self) -> TokenUsage | None:
        return self._usage

    @property
    def finish(self) -> FinishReason:
        return self._finish or "stop"  # 对照 TS：没等到 finish 就当 stop

    def message(self) -> Message:
        return Message(role="assistant", content=self.blocks())
