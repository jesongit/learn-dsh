"""Agent：被 loop 驱动的小机器人——只是个容器，逻辑都在 loop.py。

对照：deepseek-harness@53d1ef4a74 packages/agent-loop/src/agent.ts 的
LoopAgent。v0 简化：没有 abort（M2）、没有 status 事件、没有 start()
返回 disposer 的生命周期（harness 为热重载服务，我们没有 Cordis）。
"""

from __future__ import annotations

from pagent.inbox import Inbox, InboxMessage
from pagent.tools import ToolService
from pagent.types import ContentBlock


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
    ) -> None:
        self.id = id
        self.session = session
        self.llm = llm
        self.tools = tools
        self.model = model
        self.system_prompt = system_prompt
        self.inbox = Inbox()
        # 是否正在 turn 中——loop 维护；steer() 靠它决定走哪条通道
        self.running = False

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
