"""收件箱：agent 的排队 FIFO。

对照：deepseek-harness@53d1ef4a74 packages/agent-loop/src/inbox.ts。

v0 只有 queued 队列（turn 开头整批消费）；steering 队列（运行中插话、
step 之间消费）与「空闲挂起等新消息」的等待语义分别在 M1-03 / M2 加。
"""

from __future__ import annotations

from dataclasses import dataclass

from pagent.types import ContentBlock


@dataclass(frozen=True)
class InboxMessage:
    content: list[ContentBlock]


class Inbox:
    def __init__(self) -> None:
        self._queued: list[InboxMessage] = []

    @property
    def has_queued(self) -> bool:
        return bool(self._queued)

    def enqueue(self, message: InboxMessage) -> None:
        self._queued.append(message)

    def drain_queued(self) -> list[InboxMessage]:
        """整批取走排队消息（turn 开头调用）。"""
        drained = self._queued.copy()
        self._queued.clear()
        return drained
