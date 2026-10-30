"""Agent：被 loop 驱动的小机器人——只是个容器，逻辑都在 loop.py。

对照：deepseek-harness@53d1ef4a74 packages/agent-loop/src/agent.ts 的
LoopAgent。v0 简化：没有 abort（M2）、没有 status 事件、没有 start()
返回 disposer 的生命周期（harness 为热重载服务，我们没有 Cordis）。
"""

from __future__ import annotations

import asyncio

from pagent.core.inbox import Inbox, InboxMessage
from pagent.tools.registry import ToolService
from pagent.core.types import ContentBlock


class Agent:
    def __init__(
        self,
        id: str,
        session,  # pagent.session.Session（避免循环 import，运行时才有类型）
        llm,      # pagent.adapter.LlmService
        tools: ToolService,
        model: str = "default",
        system_prompt: str | None = None,
        max_steps: int | None = None,  # 单个 turn 的 step 上限（防跑飞；None=不限）
        max_input_tokens: int | None = None,  # M4-02：单请求 input 预算，逼近即触发压缩（None=不限）
    ) -> None:
        self.id = id
        self.session = session
        self.llm = llm
        self.tools = tools
        self.model = model
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.max_input_tokens = max_input_tokens
        self.inbox = Inbox()
        # 是否正在 turn 中——loop 维护；steer() 靠它决定走哪条通道
        self.running = False
        # 永续循环任务句柄（start 创建；abort 靠它发取消信号）
        self._task: asyncio.Task | None = None

    def send(self, content: list[ContentBlock]) -> None:
        """排队一条用户输入；loop 在下个 turn 开头整批消费。"""
        self.inbox.enqueue(InboxMessage(content=content))

    def steer(self, content: list[ContentBlock]) -> None:
        """运行中插话走 steering 快速通道；空闲时降级为普通排队。"""
        if self.running:
            self.inbox.steer(InboxMessage(content))
        else:
            self.send(content)

    def inject(self, content: list[ContentBlock]) -> None:
        """上下文注入：只落日志（投影时包 <context> 信封），不触发 turn。"""
        self.session.append("context/message", {"content": content})

    # ── TODO(C)：start —— 启动永续循环 ── M2-02 亲手写 ───────────────
    # 语义：create_task 把 run_loop 挂成常驻任务，句柄存 self._task 并返回。
    # 注意：run_loop 在 pagent.loop，而 loop 顶层 import 了 Agent——这里用
    # 「函数内本地 import」打破循环（Python 惯用手法，注释讲明即可）。
    # def start(self) -> asyncio.Task: ...
    def start(self) -> asyncio.Task:
        from pagent.core.loop import run_loop
        self._task = asyncio.create_task(run_loop(self))
        return self._task

    # ── TODO(D)：abort —— 中断当前 turn ── M2-02 亲手写 ─────────────
    # 语义：对循环任务发 cancel 信号 → CancelledError 会在 run_turn 的
    #       某个 await 点炸出 → turn 以 reason=aborted 体面收场。
    # 伪代码：if self._task is not None: self._task.cancel()
    # def abort(self) -> None: ...
    def abort(self) -> None:
        if self._task is not None:
            self._task.cancel()