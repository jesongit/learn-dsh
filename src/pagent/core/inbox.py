"""收件箱：agent 的两条队列。

对照：deepseek-harness@53d1ef4a74 packages/agent-loop/src/inbox.ts。

queued 队列：正常输入，turn 开头整批消费。
steering 队列：运行中的插话，step 之间消费。
两条队列结构完全同构——入队 / 判空 / 整批排空各一对。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pagent.core.types import ContentBlock


@dataclass(frozen=True)
class InboxMessage:
    content: list[ContentBlock]


class Inbox:
    def __init__(self) -> None:
        self._queued: list[InboxMessage] = []
        self._steering: list[InboxMessage] = []
        # 「闹钟」：wait_for_queued 挂起时登记，enqueue 时敲响（M2-02 填逻辑）
        self._wakeup: asyncio.Future | None = None

    @property
    def has_queued(self) -> bool:
        return bool(self._queued)

    @property
    def has_steering(self) -> bool:
        return bool(self._steering)

    def enqueue(self, message: InboxMessage) -> None:
        self._queued.append(message)
        if self._wakeup is not None:
            # 来活了，叫醒
            self._wakeup.set_result(None)

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

    # ── TODO(A)：空闲挂起的「闹钟」── M2-02 亲手写 ──────────────────
    # 语义：已有排队消息 → 立即返回；否则登记 Future 挂起，
    #       直到 enqueue 敲响它（或被 cancel）才醒来。
    # 伪代码：
    #   if self.has_queued: return                     # 有活，不睡
    #   self._wakeup = asyncio.get_running_loop().create_future()
    #   try: await self._wakeup
    #   finally: self._wakeup = None                   # 醒来/被取消都要撤闹钟
    # async def wait_for_queued(self) -> None: ...

    async def wait_for_queued(self) -> None:
        if self.has_queued:
            return
        self._wakeup = asyncio.get_running_loop().create_future()
        try:
            await self._wakeup
        finally:
            self._wakeup = None

    # ── TODO(B)：enqueue 末尾加一行——敲钟 ──────────────────────────
    # 伪代码：if self._wakeup is not None: self._wakeup.set_result(None)
