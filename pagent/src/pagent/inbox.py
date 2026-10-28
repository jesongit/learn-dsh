"""收件箱：agent 的两条队列。

对照：deepseek-harness@53d1ef4a74 packages/agent-loop/src/inbox.ts。

queued 队列：正常输入，turn 开头整批消费（M1-02 已实现）。
steering 队列：运行中的插话，step 之间消费 —— M1-03 亲手写任务。
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
        # TODO(A)：第二条队列 _steering（插话专用）

    @property
    def has_queued(self) -> bool:
        return bool(self._queued)

    # TODO(B)：@property has_steering —— steering 队列非空？（对照 has_queued）

    @property
    def has_steering(self) -> bool:
        return bool(self._steering)

    def enqueue(self, message: InboxMessage) -> None:
        self._queued.append(message)

    def drain_queued(self) -> list[InboxMessage]:
        """整批取走排队消息（turn 开头调用）。"""
        drained = self._queued.copy()
        self._queued.clear()
        return drained

    def steer(self, message: InboxMessage) -> None:
        self._steering.append(message)

    def drain_steering(self) -> list[InboxMessage]:
        drained = self._steering.copy()
        self._steering.clear()
        return drained

    # TODO(C)：steer(message) —— 插话进 _steering 队列（对照 enqueue）
    # TODO(D)：drain_steering() —— 整批取走插话（对照 drain_queued；
    #          逐条对比 M1-01 的"队列消费"模式，只是换了一条队列）
