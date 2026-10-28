"""收件箱：agent 的两条队列。

对照：deepseek-harness@53d1ef4a74 packages/agent-loop/src/inbox.ts。

queued 队列：正常输入，turn 开头整批消费。
steering 队列：运行中的插话，step 之间消费。
两条队列结构完全同构——入队 / 判空 / 整批排空各一对。
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
        self._steering: list[InboxMessage] = []

    @property
    def has_queued(self) -> bool:
        return bool(self._queued)

    @property
    def has_steering(self) -> bool:
        return bool(self._steering)

    def enqueue(self, message: InboxMessage) -> None:
        self._queued.append(message)

    def steer(self, message: InboxMessage) -> None:
        self._steering.append(message)

    def drain_queued(self) -> list[InboxMessage]:
        """整批取走排队消息（turn 开头调用）。"""
        drained = self._queued.copy()
        self._queued.clear()
        return drained

    def drain_steering(self) -> list[InboxMessage]:
        """整批取走插话（step 之间调用）。"""
        drained = self._steering.copy()
        self._steering.clear()
        return drained
