"""M2-02 测试：挂起唤醒 / 中断收场（mock 'hang' 条目模拟模型卡住）。

测试即规格：读断言 = 读「挂起 + abort」的契约。
"""

from __future__ import annotations

import asyncio

from pagent.llm.adapter import LlmService
from pagent.core.agent import Agent
from pagent.core.inbox import Inbox, InboxMessage
from pagent.llm.mock import MockAdapter
from pagent.core.session import Session
from pagent.tools.registry import ToolService
from pagent.core.types import TextBlock


def test_wait_for_queued_wakes_on_enqueue():
    """契约：挂起的等待在 enqueue 后被唤醒（超时=没醒=挂起失败）。"""
    inbox = Inbox()

    async def run() -> None:
        waiter = asyncio.create_task(inbox.wait_for_queued())
        await asyncio.sleep(0.01)
        assert not waiter.done()  # 没消息：应该还睡着
        inbox.enqueue(InboxMessage(content=[TextBlock(text="hi")]))
        await asyncio.wait_for(waiter, timeout=1)  # 敲钟后醒来

    asyncio.run(run())


def _make_agent(script) -> tuple[Agent, Session, MockAdapter]:
    session = Session("test-session")
    llm = LlmService()
    adapter = MockAdapter(script)
    llm.register(["mock"], adapter)
    agent = Agent(id="a1", session=session, llm=llm, tools=ToolService(), model="mock")
    return agent, session, adapter


def test_abort_mid_stream_ends_turn_aborted():
    """契约：流式中途 abort → step/end 照落、无 error 事件、turn/end reason=aborted。"""
    agent, session, adapter = _make_agent(["hang"])
    agent.send([TextBlock(text="hi")])

    async def run() -> None:
        task = agent.start()
        for _ in range(100):  # 等 hang 挂起（partial chunk 已落日志）
            await asyncio.sleep(0.01)
            if any(e.type == "assistant/chunk" for e in session.events):
                break
        agent.abort()
        await asyncio.wait_for(task, timeout=1)  # 1 秒内必须体面退场

    asyncio.run(run())

    types = [e.type for e in session.events]
    ends = [e for e in session.events if e.type == "turn/end"]
    assert ends and ends[-1].data["reason"] == "aborted"
    assert "step/end" in types  # 叙事合上
    assert "error" not in types  # 中止不是事故


def test_abort_while_idle_task_ends_cleanly():
    """契约：空闲时 abort——没有 turn 可收，任务直接结束。"""
    agent, session, adapter = _make_agent([])

    async def run() -> None:
        task = agent.start()
        await asyncio.sleep(0.01)  # 已挂起等待
        agent.abort()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(run())

    assert not [e for e in session.events if e.type == "turn/start"]
