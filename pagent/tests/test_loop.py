"""M1-02 测试：复现 harness loop.spec.ts 的场景 1。

场景出处：deepseek-harness@53d1ef4a74 packages/agent-loop/tests/loop.spec.ts #1
  "runs a simple turn: queued message → model → idle, with ordered events"

断言由 AI 按行为规格补全（参考实现，用户要求）；被测实现 loop.py 的
TODO(1)~(10) 由用户亲手写。测试即规格：读断言 = 读 loop 的契约。
"""

from __future__ import annotations

import asyncio

from pagent.adapter import LlmService
from pagent.agent import Agent
from pagent.loop import run_loop
from pagent.mock import MockAdapter, text_response
from pagent.session import Session
from pagent.tools import ToolService
from pagent.types import Message, TextBlock


def _make_agent(script: list[list]) -> tuple[Agent, Session, MockAdapter]:
    """排戏助手：拼一个 mock 模型的 agent，返回 (agent, session, adapter)。"""
    session = Session("test-session")
    llm = LlmService()
    adapter = MockAdapter(script)
    llm.register(["mock"], adapter)
    agent = Agent(
        id="a1",
        session=session,
        llm=llm,
        tools=ToolService(),
        model="mock",
        system_prompt=None,
    )
    return agent, session, adapter


def test_simple_turn_ordered_events():
    """场景 1：排队消息 → 一次模型请求 → 回到空闲，事件按序落日志。"""
    agent, session, adapter = _make_agent([text_response("你好")])
    agent.send([TextBlock(text="hi")])

    asyncio.run(run_loop(agent))

    types = [e.type for e in session.events]

    # 规格 1：事件骨架按序——把 chunk 抽掉后应恰好是这个序列
    skeleton = [t for t in types if t != "assistant/chunk"]
    assert skeleton == [
        "user/message", "turn/start", "step/start",
        "assistant/message", "step/end", "turn/end",
    ], f"事件骨架不符：{skeleton}"

    # chunk 全数落日志：text_response("你好") 共 6 个 chunk
    # （BlockStart、2×TextDelta、BlockEnd、Usage、Finish——每个都记，不只 delta）
    assert types.count("assistant/chunk") == 6, f"chunk 落日志数不对：{types.count('assistant/chunk')}"

    # chunk 位于 step/start 之后、assistant/message 之前（流式期间产生的记录）
    assert types.index("step/start") < types.index("assistant/chunk") < types.index("assistant/message")

    # 规格 2：开轮——第 1 轮，触发是消息
    turn_start = session.events[types.index("turn/start")]
    assert turn_start.data == {"turn": 1, "trigger": {"kind": "message"}}

    # 规格 3：关轮——第 1 轮，正常完成（模型没调工具，不欠工作）
    turn_end = session.events[types.index("turn/end")]
    assert turn_end.data == {"turn": 1, "reason": "completed"}

    # 规格 4：assistant/message 的内容是组装完的整条消息
    assistant_event = session.events[types.index("assistant/message")]
    assert assistant_event.data["turn"] == 1 and assistant_event.data["step"] == 1
    assert assistant_event.data["content"] == [TextBlock(text="你好")]

    # 规格 5：投影恰好两条——user 和 assistant；chunk 事件不进历史
    messages = session.derive_messages()
    assert messages == [
        Message(role="user", content=[TextBlock(text="hi")]),
        Message(role="assistant", content=[TextBlock(text="你好")]),
    ]

    # 规格 6：请求在 assistant 落日志之前组装（时间顺序铁证）——
    # 若顺序反了（先落 assistant 再组装请求），投影会包含它，这里就会是 2 条
    assert len(adapter.requests) == 1
    sent = adapter.requests[0]
    assert sent.model == "mock"
    assert sent.messages == [Message(role="user", content=[TextBlock(text="hi")])]
