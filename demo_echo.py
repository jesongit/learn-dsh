"""echo demo —— M2-03：终端真模型对话（M2 收官集成）。

跑法：  uv run python demo_echo.py
玩法：  流式真聊；输出中途 /stop 中断；聊长问题时 /steer <新指示> 中途插话；
        quit 退出。

你要写的：TODO(G) 把接线从 EchoAdapter 换到 DeepSeekAdapter（seam 兑现时刻）；
TODO(H) 给 runner 加 /steer 命令。工具注册本节刻意移除——工具结果的真实
wire format 是 M3 的主菜（预告：现在接工具，模型会「看不到结果」而反复调用）。
EchoAdapter 与 mock 函数保留在文件里，作为三种 mock 风格的纪念品与测试基建。
"""

from __future__ import annotations

import asyncio
import json
import os

from demo_smoke import load_env  # 复用冒烟脚本的 .env 读取（单一来源）
from pagent.adapter import LLMAdapter, LlmService
from pagent.agent import Agent
from pagent.deepseek import DeepSeekAdapter
from pagent.loop import run_loop
from pagent.session import Session
from pagent.tools import ToolService
from pagent.types import (
    BlockEnd,
    BlockStart,
    Finish,
    GenerateOptions,
    Message,
    StreamChunk,
    TextBlock,
    TextDelta,
    TokenUsage,
    ToolCallBlock,
    ToolCallDelta,
    ToolResultBlock,
    UsageChunk,
)
from pagent.mock import text_response, tool_call_response


class EchoAdapter(LLMAdapter):
    """规则式假模型：替模型回答——按「对话进行到哪一步」选规则。

    对话状态机（按序判断，命中即 yield 对应响应后返回）——

    状态① 「用户刚下了 echo 指令，tools 还没执行过」
        获取用户最新输入，以 "echo " 开头，且本轮尚未执行过 tools
        （判断：最新用户文本以 "echo " 开头，且末条消息无 ToolResultBlock
          ——末条消息还是用户的话，说明工具结果从没回来过）
        → 替模型走流程：先说 "让我 echo 一下."，
          再发 tool_call_response("call-echo", "echo", {"text": 去前缀文本})
          ——「模型想调工具」= 在响应里放 ToolCallBlock，loop 会替它执行

    状态② 「tools 已执行完，结果刚回填」
        判断：末条消息 content 里是 ToolResultBlock
          （工具结果由 loop 回填，投影后永远排在消息末尾——M1-02 投影规则）
        → 替模型总结收尾："The echo tool has spoken."
          （不再调工具 → finish=stop → 方向盘判停，turn 结束）

    状态③ 「普通聊天，没有 echo 指令」
        判断：以上都不满足
        → 正常接话：text_response(f'你说："{文本}"。试试 echo <内容>')

    辅助（伪代码）：
      末条用户文本 ← 逆序首个 role=="user" 消息的首个 TextBlock，缺省 ""
      有工具结果 ← options.messages[-1].content 中存在 ToolResultBlock

    ── 输入长什么样（用户输入 "echo 你好" 后的两轮请求）──

    Round 1 的 options.messages：
        [
            Message(role="user",
                    content=[TextBlock(text="echo 你好")]),
        ]
        末条用户文本 = "echo 你好"（倒序首个 role=="user"）
        末条消息无 ToolResultBlock
        → 命中①：回一句话 + 调 echo 工具

    Round 2 的 options.messages（工具执行完，loop 回填后再次请求）：
        [
            Message(role="user",
                    content=[TextBlock(text="echo 你好")]),
            Message(role="assistant",
                    content=[ToolCallBlock(id="call-echo", name="echo",
                                           arguments='{"text": "你好"}')]),
            Message(role="user",                                  # ← 末条
                    content=[ToolResultBlock(tool_call_id="call-echo",
                                             content=[TextBlock(text="echo: 你好")],
                                             is_error=False)]),
        ]
        末条用户文本仍是 "echo 你好"（倒序首个 user，跳过中间的 assistant）
        但末条消息带 ToolResultBlock → ① 落选 → 命中② 收尾

    为什么倒序：投影是全量累积的——多轮对话后 messages 里有**多条**
    user 消息（每轮输入都留在日志里），最新的在最后面；
    倒序首个 = 最新输入；正序首个 = 最早那句旧指令，判断就错了。
    """

    async def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        # Adapter 负责把 模型的 chunk 返回
        user_msgs = [msg for msg in reversed(options.messages) if msg.role=="user"]
        last_user_content = user_msgs[0].content[0]
        if isinstance(last_user_content, ToolResultBlock):
            # 执行过工具
            chunks = text_response("The echo tool has spoken.")
        elif isinstance(last_user_content, TextBlock) and last_user_content.text.startswith("echo "):
            text = last_user_content.text[5:]
            chunks =  text_response("让我 echo 一下.") \
                + tool_call_response("call-echo", "echo", {"text": text})
        else:
            chunks = text_response(f'你说："{last_user_content.text}"。试试 echo <内容>')
        for chunk in chunks:
            yield chunk

        # raise NotImplementedError("TODO(A)~(C)：按 docstring 的三条规则实现")


class TerminalUI(LLMAdapter):
    """终端回显装饰器：包住任何 adapter，流式期间把文本增量打到屏幕。

    seam 可以叠 seam——UI 不改变模型行为，只是"旁听"chunk 流。
    （这就是 M2 网页流式渲染的雏形。）
    """

    def __init__(self, inner: LLMAdapter) -> None:
        self._inner = inner

    async def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        async for chunk in self._inner.stream(options):
            if isinstance(chunk, TextDelta):
                print(chunk.text, end="", flush=True)
            yield chunk


def build_agent() -> Agent:
    load_env()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY：复制 .env.example 为 .env 并填入")

    session = Session("echo-demo")
    llm = LlmService()
    tools = ToolService()  # 刻意不注册工具——原因见 TODO(G) 注释

    # ── TODO(G)：换真模型 ── M2-03 亲手写 ───────────────────────────
    # 语义：seam 兑现——注册表里换 adapter、模型名指过去，其余代码零改动。
    # 伪代码：
    #   llm.register(["deepseek-chat"], TerminalUI(DeepSeekAdapter(api_key)))
    #   Agent(..., model="deepseek-chat")
    # （mock 时代的 echo 工具注册与 EchoAdapter 接线整体退役——文件里保留作纪念）
    llm.register(["deepseek-chat"], TerminalUI(DeepSeekAdapter(api_key)))

    agent = Agent(
        id="deepseek",
        session=session,
        llm=llm,
        tools=tools,
        model="deepseek-chat",
        system_prompt="你是 PAgent 的演示 agent。",
        max_steps=8,  # 防跑飞闸
    )
    return agent


async def main() -> None:
    agent = build_agent()
    agent.start()  # 永续循环常驻——不再是「一行输入 asyncio.run 一次」
    print("PAgent echo demo（quit 退出；/stop 中断；试试：echo 你好）")
    while True:
        try:
            line = await asyncio.to_thread(input, "你> ")  # input 阻塞，丢线程里跑
        except (EOFError, KeyboardInterrupt):
            agent.abort()
            break
        line = line.strip()
        if not line:
            continue
        if line == "quit":
            agent.abort()
            break
        if line == "/stop":
            print("  [abort] 中断当前 turn…")
            agent.abort()
            continue
        if line.startswith("/steer "):
            input_str = line.removeprefix("/steer ")
            agent.steer([TextBlock(text=input_str)])
            print(f"  [steer] 已插话 {input_str}")
            continue
        # ── TODO(H)：/steer 命令 ── M2-03 亲手写 ────────────────────
        # 语义：把 "/steer " 之后的内容作为插话转给 agent.steer()
        #       （steer 只在 turn 运行中走快速通道——空闲时自动降级为排队）。
        # 伪代码：
        #   if line.startswith("/steer "):
        #       agent.steer([TextBlock(text=line[7:])])
        #       print("  [steer] 已插话"); continue

        # 其他语句直接发进去
        agent.send([TextBlock(text=line)])
        print("PAgent> ", end="", flush=True)
        # 等 turn 落幕（粗轮询；事件驱动版 M2-03 再打磨）
        # 注意：真模型有延迟——发出后日志可能还是空的，不能用 events[-1] 起手
        seen = len(agent.session.events)
        last = None
        for _ in range(300):  # 最多等 30s
            await asyncio.sleep(0.1)
            events = agent.session.events
            if len(events) > seen and events[-1].type == "turn/end":
                last = events[-1]
                break
        print()
        if last is not None and last.type == "turn/end":
            print(f"  [turn{last.data['turn']} 结束，原因: {last.data['reason']}]")
    print("再见。")


if __name__ == "__main__":
    asyncio.run(main())
