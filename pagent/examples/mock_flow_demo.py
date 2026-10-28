"""数据流演示：一份「模型回答」从作者到日志的完整旅程。

跑法：  uv run python examples/mock_flow_demo.py
说明：  第一、二部分现在就能跑；第三部分要等你实现 loop.py 的 run_turn
        之后才完整——实现完重跑本文件，就是 M1-02 的收尾演示。

角色表（一个都不能少）：
  ┌─ 剧作家  text_response / tool_call_response ── 产出一次完整响应（一串 chunk）
  ├─ 排戏人  测试/demo 的作者（你）──────────────── 把几条响应排成剧本 script
  ├─ 演员    MockAdapter.stream() ──────────────── 照本宣科：pop 一条响应逐 chunk 吐
  ├─ 导演    run_loop（M1-02 你在写）────────────── 组装 options、调演员、把 chunk 记日志
  └─ 舞台    Session ────────────────────────────── 所有事件最终落在这本唯一日志上

完整调用链（谁调用谁，参数是什么）：

    你（排戏人）
      │ 构造时把剧本塞进演员                       【构造门：script】
      ▼
    MockAdapter(script) ──注册──> LlmService ──挂──> Agent.llm
      ▲
      │ agent.send("hi")                            【用户输入】
      │
    run_loop(agent)                                 【导演开工】
      │ 组装 options = GenerateOptions(messages=session.derive_messages(), ...)
      │                                             【请求门：options，每次调用都来】
      ▼
    MockAdapter.stream(options)
      │ 1. options 只记账不阅读（self.requests.append）
      │ 2. self.script.pop(0) 取走下一条响应
      │ 3. 逐个 yield chunk ──────────────────────  【答案的出处就是这个列表】
      ▼
    run_loop：chunk 先落 session 日志，再喂 BlockAssembler
      ▼
    assistant/message 落日志 → derive_messages() 投影 → 变成下一次请求的 options
                                                      └──────── 数据闭环就在这 ────────┘
"""

import asyncio

from pagent.adapter import LlmService
from pagent.agent import Agent
from pagent.mock import MockAdapter, text_response, tool_call_response
from pagent.session import Session
from pagent.tools import ToolService
from pagent.types import GenerateOptions, Message, TextBlock


def part0_the_playwright():
    """第一幕 · 剧作家的产物：一次响应 = 一串 chunk。

    数据来源：text_response 的参数是你给的一句话；
    返回值是按「五拍节奏」拆好的 chunk 列表——这就是剧本的最小单元。
    """
    print("=" * 60)
    print("第一幕：剧作家的产物（一次响应）")
    response = text_response("你好")
    for chunk in response:
        print(f"  {chunk}")


def part1_direct_stream():
    """第二幕 · 没有 loop 的直接消费：现在就能跑。

    谁调用 stream？——本函数（扮演导演的角色，手工组装 options）。
    options 从哪来？——调用方组装的「问题」；真实世界里由 loop 用
    derive_messages() 投影产出，这里为了演示手工造一份。
    script 从哪来？——构造时塞进去的，注意两次请求消费两条响应，
    第三次触发「脚本耗尽」。requests 记下每次收到的 options。
    """
    print("=" * 60)
    print("第二幕：直接调演员（无 loop）")

    # 排戏人排两幕剧：第一幕调工具，第二幕总结
    script = [
        tool_call_response("call-1", "fetch_weibo_hot_search", {}, text="让我查一下"),
        text_response("今天热搜第一是……"),
    ]
    llm = LlmService()
    llm.register(["mock"], MockAdapter(script))  # 剧本从构造门进

    options = GenerateOptions(
        model="mock",
        messages=[Message(role="user", content=[TextBlock(text="总结热搜")])],
    )

    async def consume() -> None:
        adapter = llm._adapters["mock"]
        for round_no in (1, 2, 3):  # 第三次故意超支，演示脚本耗尽
            print(f"  ── 第 {round_no} 次请求（options 记账前 requests={len(adapter.requests)} 条）")
            try:
                async for chunk in llm.stream(options):
                    print(f"    收到 chunk: {chunk}")
            except RuntimeError as e:
                print(f"    ✗ {e}")
            print(f"    （记账后 requests={len(adapter.requests)} 条——options 被记录但从未被阅读）")

    asyncio.run(consume())


def part2_through_the_agent():
    """第三幕 · 完整链路：导演开工（等你实现 run_turn 后重跑）。

    谁调用 stream？——run_loop（你正在写的 loop.py）。
    此时 options 不再手工造，而是 session.derive_messages() 的投影。
    跑完打印整本事件日志——剧本的两幕会变成日志里的完整故事。
    """
    print("=" * 60)
    print("第三幕：经过 agent 的完整链路")

    script = [
        tool_call_response("call-1", "fetch_weibo_hot_search", {"limit": 10}),
        text_response("今天热搜第一是……（总结）"),
    ]
    session = Session("demo")
    llm = LlmService()
    llm.register(["mock"], MockAdapter(script))
    tools = ToolService()
    tools.register(
        name="fetch_weibo_hot_search",
        description="抓取微博热搜榜",
        parameters={},
        fn=lambda limit=10: [{"rank": 1, "title": "示例热搜", "heat": 9_999}],
    )
    agent = Agent("demo-agent", session, llm, tools, model="mock")
    agent.send([TextBlock(text="帮我总结今天的热搜")])

    try:
        from pagent.loop import run_loop
        asyncio.run(run_loop(agent))
    except NotImplementedError:
        print("  ⏳ loop.py 还没实现（NotImplementedError）——完成 TODO(1)~(10) 后重跑本文件")
        return

    print("  事件日志（type + 关键数据）：")
    for event in session.events:
        print(f"    [{event.seq:2d}] {event.type}: {event.data}")
    print("  投影出的模型历史：")
    for message in session.derive_messages():
        print(f"    {message.role}: {message.content}")


if __name__ == "__main__":
    part0_the_playwright()
    part1_direct_stream()
    part2_through_the_agent()
