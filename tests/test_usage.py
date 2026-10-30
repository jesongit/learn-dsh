"""M4-01 作业区：token 记账（测试即规格）。

TODO(G) 在 src/pagent/deepseek.py（translate_event）、TODO(M) 在
src/pagent/loop.py、TODO(N) 在 src/pagent/session.py——三条 skip 挂起，
按 G → M → N 逐条解锁（删对应 skip），全绿 = 本节完成。

注意：
- test_usage_frame_translates 锁的是**假设形状**：TODO(G) 编码第一步是
  采样真实 wire（见 TODO(G) 注释）——若真实帧与样例不同，测试与实现
  一起改，两处必须同步。
- 记账事件用真实 dataclass（TokenUsage 是 frozen dataclass，相等比较
  直接可用）。
"""

from __future__ import annotations

import pytest

from pagent.adapter import LlmService
from pagent.agent import Agent
from pagent.deepseek import DeepSeekAdapter
from pagent.loop import run_until_idle
from pagent.mock import MockAdapter, text_response, tool_call_response
from pagent.session import Session
from pagent.tools import ToolService
from pagent.types import TextBlock, TokenUsage, UsageChunk



def test_usage_frame_translates():
    """契约：usage 帧 → UsageChunk（TokenUsage 命名换算：prompt=input）。"""
    event = {"choices": [], "usage": {"prompt_tokens": 100,
                                      "completion_tokens": 50,
                                      "total_tokens": 150}}
    chunks = DeepSeekAdapter.translate_event(event)
    assert chunks == [UsageChunk(usage=TokenUsage(input_tokens=100, output_tokens=50))]



def test_loop_records_usage_events():
    """契约：每个响应的 UsageChunk 记成 assistant/usage 事件（账本与内容分流）。

    场景用工具流制造两次请求（纯文本响应一步就关轮，只有一笔账）：
    step 1 工具调用（方向盘续一步）→ step 2 文本收尾。
    """
    session = Session("test-usage")
    llm = LlmService()
    adapter = MockAdapter([
        tool_call_response("c1", "echo", {}),  # step 1
        text_response("done"),                  # step 2
    ])
    llm.register(["mock"], adapter)
    agent = Agent(id="a1", session=session, llm=llm,
                  tools=ToolService(), model="mock")
    agent.send([TextBlock(text="跑两步")])

    import asyncio
    asyncio.run(run_until_idle(agent))

    usage_events = [e for e in session.events if e.type == "assistant/usage"]
    assert len(usage_events) == 2  # 两个 step 各一次请求、各记一笔
    assert usage_events[0].data["usage"] == TokenUsage(input_tokens=10, output_tokens=2)
    assert usage_events[1].data["usage"] == TokenUsage(input_tokens=10, output_tokens=4)
    # 账本与内容分流：chunk 事件里不再有 UsageChunk
    leaked = [e for e in session.events
              if e.type == "assistant/chunk"
              and isinstance(e.data["chunk"], UsageChunk)]
    assert leaked == [], f"UsageChunk 仍混在 chunk 事件里：{leaked}"



def test_usage_report_sums():
    """契约：usage_report 是日志的投影——汇总全部 assistant/usage 事件。"""
    session = Session("test-report")
    llm = LlmService()
    adapter = MockAdapter([
        tool_call_response("c1", "echo", {}),  # step 1：(10, 2)
        text_response("done"),                  # step 2：(10, 4)
    ])
    llm.register(["mock"], adapter)
    agent = Agent(id="a1", session=session, llm=llm,
                  tools=ToolService(), model="mock")
    agent.send([TextBlock(text="跑两步")])

    import asyncio
    asyncio.run(run_until_idle(agent))

    report = session.usage_report()
    assert report == {"input_tokens": 20, "output_tokens": 6}
