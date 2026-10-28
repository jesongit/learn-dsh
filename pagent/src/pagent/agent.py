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

    # TODO(E)：steer(content) —— 运行中插话：
    #   self.running 为 True → self.inbox.steer(InboxMessage(content))
    #   否则（空闲）→ 降级为 self.send(content)（插话变排队，等价于新输入）

    # TODO(F)：inject(content) —— 上下文注入，不触发 turn：
    #   self.session.append("context/message", {"content": content})
    #   （投影时 session 会自动包上 <context> 信封——看 session.py 的
    #    derive_messages，这个分支脚手架已经写好了）
