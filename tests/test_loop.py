"""M1-02 测试：复现 harness loop.spec.ts 的场景 1。

场景出处：deepseek-harness@53d1ef4a74 packages/agent-loop/tests/loop.spec.ts #1
  "runs a simple turn: queued message → model → idle, with ordered events"

断言由 AI 按行为规格补全（参考实现，用户要求）；被测实现 loop.py 的
TODO(1)~(10) 由用户亲手写。测试即规格：读断言 = 读 loop 的契约。
"""

from __future__ import annotations

import asyncio

from pagent.llm.adapter import LlmService
from pagent.core.agent import Agent
from pagent.core.loop import run_until_idle
from pagent.llm.mock import MockAdapter, text_response, tool_call_response
from pagent.core.session import Session
from pagent.tools.registry import ToolService
from pagent.core.types import Message, TextBlock


def _make_agent(script: list) -> tuple[Agent, Session, MockAdapter]:
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

    asyncio.run(run_until_idle(agent))

    types = [e.type for e in session.events]

    # 规格 1：事件骨架按序——把内容流（chunk）与记账（usage）抽掉后
    # 应恰好是这个序列（M4-01 起 UsageChunk 分流成 assistant/usage 事件）
    skeleton = [t for t in types if t not in ("assistant/chunk", "assistant/usage")]
    assert skeleton == [
        "user/message", "turn/start", "step/start",
        "assistant/message", "step/end", "turn/end",
    ], f"事件骨架不符：{skeleton}"

    # chunk 全数落日志：text_response("你好") 共 6 个 chunk，其中 1 个
    # UsageChunk 分流去账本，剩 5 个记 assistant/chunk
    # （BlockStart、2×TextDelta、BlockEnd、Finish——每个都记，不只 delta）
    assert types.count("assistant/chunk") == 5, f"chunk 落日志数不对：{types.count('assistant/chunk')}"
    assert types.count("assistant/usage") == 1, "usage 应分流记账，不混在 chunk 里"

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


def _all_text(messages: list[Message]) -> str:
    """把一组消息里的所有 TextBlock 拼成一个字符串（断言辅助）。"""
    return "".join(
        b.text for m in messages for b in m.content if isinstance(b, TextBlock)
    )


# ── 场景 5：运行中插话（steering），继续当前 turn ────────────────────────────

def test_steering_between_steps_continues_turn():
    """harness spec #5：step 之间收到插话 → 落 steering/message → 继续本 turn。"""
    # 排戏：第一条响应是「函数条目」——模型流式返回期间，模拟用户插话。
    # agent 用闭包晚绑定：函数在流式时才被调用，那时 agent 已存在。
    def steer_during_first_response(options):
        agent.steer([TextBlock(text="只要前 3 条")])
        return text_response("先看看热搜")

    agent, session, adapter = _make_agent(
        [steer_during_first_response, text_response("好的，只看前 3 条")]
    )
    agent.send([TextBlock(text="总结热搜")])

    asyncio.run(run_until_idle(agent))

    types = [e.type for e in session.events]

    # 插话没有开新 turn：仍然只有一个 turn，但有两个 step
    assert types.count("turn/start") == 1
    assert types.count("step/start") == 2

    # 插话以 steering/message 落日志，位置在 step1/end 之前（harness 顺序：
    # 先排插话 → 再记 step/end → 最后方向盘决策）
    assert types.count("steering/message") == 1
    assert types.index("steering/message") < types.index("step/end")

    # 第二次请求里模型看到了插话（带 <steering> 信封的投影）
    assert "只要前 3 条" in _all_text(adapter.requests[1].messages)
    assert "<steering>" in _all_text(adapter.requests[1].messages)


# ── 场景 6：空闲时 steer 等价于 send ────────────────────────────────────────

def test_steer_while_idle_behaves_like_send():
    """harness spec #6：没有 turn 在跑，steer() 降级为 send（排队开新轮）。"""
    agent, session, adapter = _make_agent([text_response("你好")])

    agent.steer([TextBlock(text="hi")])  # 此时 agent.running=False
    asyncio.run(run_until_idle(agent))

    types = [e.type for e in session.events]
    # 走的是排队通道：user/message 开路、正常一个 turn，而不是 steering/message
    assert types[0] == "user/message"
    assert types.count("turn/start") == 1
    assert types.count("steering/message") == 0


# ── 场景 7：inject() 注入上下文，不触发 turn ─────────────────────────────────

def test_inject_adds_context_without_turn():
    """harness spec #7：注入的上下文落日志、对下次请求可见，但不开启 turn。"""
    agent, session, adapter = _make_agent([text_response("收到")])

    agent.inject([TextBlock(text="背景资料：昨日热搜数据")])
    agent.send([TextBlock(text="总结热搜")])
    asyncio.run(run_until_idle(agent))

    types = [e.type for e in session.events]
    # 注入落了日志（context/message），但没有为它开 turn
    assert types.count("context/message") == 1
    assert types.index("context/message") < types.index("user/message")
    assert types.count("turn/start") == 1

    # 模型在请求里看到带 <context> 信封的注入 + 正常用户消息
    assert "背景资料" in _all_text(adapter.requests[0].messages)
    assert "<context>" in _all_text(adapter.requests[0].messages)
    assert "总结热搜" in _all_text(adapter.requests[0].messages)


# ── 场景 12：连续排队消息链接成连续 turn ────────────────────────────────────

def test_queued_messages_chain_into_consecutive_turns():
    """harness spec #12：第二条消息在 turn1 运行期间到达 → 排队 → 链接成 turn2。"""
    # 排戏：第一条响应期间，模拟用户趁 agent 干活又发了一条
    def send_second_during_first(options):
        agent.send([TextBlock(text="问题二")])
        return text_response("第一问的回答")

    agent, session, adapter = _make_agent(
        [send_second_during_first, text_response("第二问的回答")]
    )
    agent.send([TextBlock(text="问题一")])

    asyncio.run(run_until_idle(agent))

    # 两个 turn，编号 1、2
    starts = [e for e in session.events if e.type == "turn/start"]
    assert [e.data["turn"] for e in starts] == [1, 2]
    assert len(adapter.requests) == 2

    # 第二次请求 = turn1 完整历史 + 问题二（投影跨 turn 累积——LLM 无状态，
    # 「记得上一问」全靠投影全量）
    assert adapter.requests[1].messages == [
        Message(role="user", content=[TextBlock(text="问题一")]),
        Message(role="assistant", content=[TextBlock(text="第一问的回答")]),
        Message(role="user", content=[TextBlock(text="问题二")]),
    ]


# ── 场景 14：模型错误以 reason=error 结束 turn ──────────────────────────────

def test_model_error_ends_turn_with_reason_error():
    """harness spec #14：adapter 抛异常 → 落 error 事件 → turn/end(reason=error)。

    注意与工具失败的区别：工具失败是「数据」（is_error 结果回模型，turn 继续）；
    模型本身炸了是「turn 级失败」——本轮没法继续，以 error 收场。
    """
    def boom(options):
        raise RuntimeError("模型炸了")

    agent, session, adapter = _make_agent([boom])
    agent.send([TextBlock(text="hi")])

    asyncio.run(run_until_idle(agent))  # 异常必须在 loop 内部消化，不该传出来

    types = [e.type for e in session.events]
    skeleton = [t for t in types if t != "assistant/chunk"]
    # 顺序：step/end 照常落（日志叙事完整），然后 error，最后带原因关轮
    assert skeleton == [
        "user/message", "turn/start", "step/start",
        "step/end", "error", "turn/end",
    ], f"事件骨架不符：{skeleton}"

    error_event = session.events[types.index("error")]
    assert error_event.data["turn"] == 1 and error_event.data["step"] == 1
    assert "模型炸了" in error_event.data["message"]

    assert session.events[types.index("turn/end")].data == {"turn": 1, "reason": "error"}
    # turn 已死：没有第二次请求
    assert len(adapter.requests) == 1


# ── max_steps：跑飞的保护闸 ─────────────────────────────────────────────────

def test_max_steps_truncates_runaway_loop():
    """模型连调工具不停 → max_steps 到顶截断，reason=max-steps，多余脚本不消费。"""
    agent, session, adapter = _make_agent(
        [
            tool_call_response("c1", "echo", {}),
            tool_call_response("c2", "echo", {}),
            tool_call_response("c3", "echo", {}),  # 第 3 条不该被消费
        ]
    )
    agent.max_steps = 2
    agent.send([TextBlock(text="跑起来")])

    asyncio.run(run_until_idle(agent))

    types = [e.type for e in session.events]
    assert types.count("step/start") == 2
    assert types.count("tool/call") == 2
    assert session.events[types.index("turn/end")].data == {"turn": 1, "reason": "max-steps"}
    assert len(adapter.requests) == 2
