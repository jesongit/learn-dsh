"""M1-02 测试：复现 harness loop.spec.ts 的场景 1（断言由你亲手写）。

场景出处：deepseek-harness@53d1ef4a74 packages/agent-loop/tests/loop.spec.ts #1
  "runs a simple turn: queued message → model → idle, with ordered events"

你写的是**行为规格**：把下面的预期翻译成断言。别改 Arrange 部分。
"""

from __future__ import annotations

import asyncio

from pagent.adapter import LlmService
from pagent.agent import Agent
from pagent.loop import run_loop
from pagent.mock import MockAdapter, text_response
from pagent.session import Session
from pagent.tools import ToolService
from pagent.types import TextBlock


def _make_agent(script: list[list]) -> tuple[Agent, Session]:
    """排戏助手：拼一个 mock 模型的 agent（AI 提供，直接用）。"""
    session = Session("test-session")
    llm = LlmService()
    llm.register(["mock"], MockAdapter(script))
    agent = Agent(
        id="a1",
        session=session,
        llm=llm,
        tools=ToolService(),
        model="mock",
        system_prompt=None,
    )
    return agent, session


def test_simple_turn_ordered_events():
    """场景 1：排队消息 → 一次模型请求 → 回到空闲，事件按序落日志。"""
    agent, session = _make_agent([text_response("你好")])
    agent.send([TextBlock(text="hi")])

    asyncio.run(run_loop(agent))

    # ---- 待验证的行为规格（把每条翻译成断言）----

    # 1. 事件类型的「骨架」按序应为（assistant/chunk 会有多个——逐字符 delta 都落了日志）：
    #    user/message → turn/start → step/start
    #    → assistant/chunk × N → assistant/message → step/end → turn/end
    # 2. turn/start 的 data：turn == 1、trigger == {"kind": "message"}
    # 3. turn/end 的 data：turn == 1、reason == "completed"
    # 4. assistant/message 的 content 是 [TextBlock(text="你好")]
    # 5. 模型历史投影正确：session.derive_messages() 恰好两条——
    #    user("hi") 和 assistant("你好")（chunk 事件不投影！）
    # 6. 模型收到的请求里只有 1 条消息：adapter.requests[0].messages 长度为 1
    #    （证明请求在 assistant 落日志**之前**组装——时间顺序的铁证）

    raise NotImplementedError("按上面的规格写断言；写完 uv run pytest -v 应 6 passed")
