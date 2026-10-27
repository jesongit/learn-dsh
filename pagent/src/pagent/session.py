"""会话：只追加的事件日志 —— 单一事实来源。

对照：deepseek-harness@53d1ef4a74 packages/session/src/index.ts。

两条铁律（来自 harness 的架构文档）：
- **模型可见即已记录**：凡是进过模型上下文的东西，必定能从这份日志重建。
- **模型历史是投影**：derive_messages() 从日志推导消息列表，日志之外
  不存在第二份真相。assistant/chunk 落日志但**不**投影——它是回放/UI 数据，
  组装完的 assistant/message 才是历史。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pagent.types import ContentBlock, Message, TextBlock, ToolResultBlock


@dataclass(frozen=True)
class SessionEvent:
    """日志中的一条不可变事实。"""

    type: str
    seq: int
    time: int  # 毫秒级时间戳
    data: dict


def _render_tagged(tag: str, content: list[ContentBlock]) -> list[ContentBlock]:
    """把注入类消息渲染成带信封的合成 user 消息（system-reminder 模式）。

    对照 harness 的 renderTagged()：模型靠信封区分「真用户说话」和
    「系统注入的上下文」。M1-03 的 steering 会用到。
    """
    return [TextBlock(text=f"<{tag}>"), *content, TextBlock(text=f"</{tag}>")]


class Session:
    """一个会话的事件日志。append 永远成功、永不阻塞——热路径不做 I/O。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self._events: list[SessionEvent] = []

    @property
    def events(self) -> list[SessionEvent]:
        return self._events

    def append(self, type: str, data: dict) -> SessionEvent:
        event = SessionEvent(
            type=type,
            seq=len(self._events),
            time=int(time.time() * 1000),
            data=data,
        )
        self._events.append(event)
        return event

    def next_turn_number(self) -> int:
        """下一个轮次号 = 日志里最后一个 turn/start 的编号 + 1（对照 loop.ts 的
        nextTurnNumber：从后往前扫，找最近一次开轮）。"""
        for event in reversed(self._events):
            if event.type == "turn/start":
                return event.data["turn"] + 1
        return 1

    def derive_messages(self) -> list[Message]:
        """把日志投影成模型历史（对照 Session.deriveMessages()）。

        关键洞察：LLM 词汇表里没有「tool」角色——工具结果作为 **user 角色**
        的消息、携带 tool-result 内容块回填（OpenAI/Anthropic 系工具回传的
        通用形态，各家的 wire format 差异由 adapter 吸收）。
        """
        messages: list[Message] = []
        for event in self._events:
            if event.type == "user/message":
                messages.append(Message(role="user", content=event.data["content"]))
            elif event.type == "assistant/message":
                messages.append(Message(role="assistant", content=event.data["content"]))
            elif event.type == "tool/result":
                messages.append(
                    Message(
                        role="user",
                        content=[
                            ToolResultBlock(
                                tool_call_id=event.data["call_id"],
                                content=event.data["content"],
                                is_error=event.data["is_error"],
                            )
                        ],
                    )
                )
            elif event.type == "context/message":
                messages.append(
                    Message(role="user", content=_render_tagged("context", event.data["content"]))
                )
            elif event.type == "steering/message":
                messages.append(
                    Message(role="user", content=_render_tagged("steering", event.data["content"]))
                )
        return messages
