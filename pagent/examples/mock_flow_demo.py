"""数据流演示：一份「模型回答」从测试到日志的完整旅程。

跑法：  uv run python examples/mock_flow_demo.py
说明：  第 1、2 部分现在就能跑；第 3 部分要等你实现 loop.py 的 run_turn
        之后才完整——实现完重跑本文件，就是 M1-02 的收尾演示。

分工（全部是测试工程的标准词汇）：
  ┌─ fixture 工厂   text_response / tool_call_response ── 构造一次完整响应（一串 chunk）
  ├─ 测试作者（你）────────────────────────────────────── Arrange 阶段把响应预注册进队列
  ├─ 测试替身 stub  MockAdapter.stream() ──────────────── 照队列回放：pop 一条响应逐 chunk 吐
  ├─ 被测系统 SUT   run_loop（M1-02 你在写）───────────── 组装 options、调替身、把 chunk 记日志
  └─ 事实源         Session ───────────────────────────── 所有事件最终落在这本唯一日志上

完整调用链（谁调用谁，参数是什么）：

    你（测试作者，Arrange 阶段）
      │ 构造替身时把预录响应队列注入                     【构造函数注入：script】
      ▼
    MockAdapter(script) ──注册──> LlmService ──挂──> Agent.llm
      ▲
      │ agent.send("hi")                               【用户输入】
      │
    run_loop(agent)                                    【被测系统运行（Act）】
      │ 组装 options = GenerateOptions(messages=session.derive_messages(), ...)
      │                                                【方法参数：options，每次调用都传】
      ▼
    MockAdapter.stream(options)
      │ 1. options 只记账不阅读（self.requests.append）
      │ 2. self.script.pop(0) 取走下一条预录响应
      │ 3. 逐个 yield chunk ────────────────────────  【答案的出处就是这个队列】
      ▼
    run_loop：chunk 先落 session 日志，再喂 BlockAssembler
      ▼
    assistant/message 落日志 → derive_messages() 投影 → 变成下一次请求的 options
                                                    └──────── 数据闭环就在这 ────────┘

为什么要预注册、依据是什么？被测的是 loop，模型输出是它依赖的外部输入；
不把输入钉死，输出就无法断言。依据是**场景规格**——「给定模型这样回，
loop 应该这样动」。整套流程就是 AAA：Arrange 备替身与输入 → Act 跑
loop → Assert 断事件日志。
"""

import asyncio

from pagent.adapter import LlmService
from pagent.agent import Agent
from pagent.mock import MockAdapter, text_response, tool_call_response
from pagent.session import Session
from pagent.tools import ToolService
from pagent.types import GenerateOptions, Message, TextBlock


def part0_fixture_factory():
    """第 1 部分 · fixture 工厂的产物：一次响应 = 一串 chunk。

    数据来源：text_response 的参数是你给的一句话；
    返回值是按「五拍节奏」拆好的 chunk 列表——这就是预录队列的最小单元。
    """
    print("=" * 60)
    print("第 1 部分：fixture 工厂的产物（一次完整响应）")
    response = text_response("你好")
    for chunk in response:
        print(f"  {chunk}")


def part1_direct_stub():
    """第 2 部分 · 绕过被测系统，直接调替身：现在就能跑。

    谁调用 stream？——本函数（临时扮演被测系统的角色，手工组装 options）。
    options 从哪来？——调用方组装的「问题」；真实世界里由 loop 用
    derive_messages() 投影产出，这里为了演示手工造一份。
    预录队列从哪来？——构造替身时注入的。注意两次请求消费两条响应，
    第三次触发「脚本耗尽」。requests 记下每次收到的 options。
    """
    print("=" * 60)
    print("第 2 部分：直接调替身（无 loop）")

    # 测试作者（Arrange）：预注册两条响应——第一条调工具，第二条总结
    script = [
        tool_call_response("call-1", "fetch_weibo_hot_search", {}, text="让我查一下"),
        text_response("今天热搜第一是……"),
    ]
    llm = LlmService()
    llm.register(["mock"], MockAdapter(script))  # 预录队列从构造函数注入

    options = GenerateOptions(
        model="mock",
        messages=[Message(role="user", content=[TextBlock(text="总结热搜")])],
    )

    async def consume() -> None:
        adapter = llm._adapters["mock"]
        for round_no in (1, 2, 3):  # 第三次故意超支，演示脚本耗尽
            print(f"  ── 第 {round_no} 次请求（记账前 requests={len(adapter.requests)} 条）")
            try:
                async for chunk in llm.stream(options):
                    print(f"    收到 chunk: {chunk}")
            except RuntimeError as e:
                print(f"    ✗ {e}")
            print(f"    （记账后 requests={len(adapter.requests)} 条——options 被记录但从未被阅读）")

    asyncio.run(consume())


def part2_through_the_sut():
    """第 3 部分 · 经过被测系统的完整链路：等你实现 run_turn 后重跑。

    谁调用 stream？——run_loop（你正在写的 loop.py）。
    此时 options 不再手工造，而是 session.derive_messages() 的投影。
    跑完打印整本事件日志——两条预录响应会变成日志里的完整故事。
    """
    print("=" * 60)
    print("第 3 部分：经过被测系统的完整链路")

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
    part0_fixture_factory()
    part1_direct_stub()
    part2_through_the_sut()
