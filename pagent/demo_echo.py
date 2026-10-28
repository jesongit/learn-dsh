"""echo demo —— 亲手点①：第一次让你的 agent 在终端里说话。

跑法：  uv run python demo_echo.py
玩法：  输入任意文字看它接话；输入 `echo 你好` 看它走一次完整的工具往返
        （模型请求调工具 → 执行 → 结果回填 → 总结）；`quit` 退出。

你要写的：EchoAdapter（TODO(A)~(C)，规则式假模型——不排剧本，第三种风格）。
其余（终端回显、echo 工具、主循环）都已备好。
"""

from __future__ import annotations

import asyncio

from pagent.adapter import LLMAdapter, LlmService
from pagent.agent import Agent
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
    """规则式假模型：看消息末尾形态选规则（对照 mock-llm.ts）。

    TODO(A)~(C)：按序判断，命中即 yield 对应响应后返回——
      ① 末条用户文本以 "echo " 开头 且 末条消息无 tool-result：
         text_response("让我 echo 一下。") + tool_call_response("call-echo", "echo", {"text": 去前缀文本})
         （两个列表相加后逐 chunk yield）
      ② 末条消息 content 含 ToolResultBlock：
         text_response("The echo tool has spoken.")
      ③ 其他：
         text_response(f'你说："{文本}"。试试 echo <内容>')

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
        

        raise NotImplementedError("TODO(A)~(C)：按 docstring 的三条规则实现")


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
    session = Session("echo-demo")
    llm = LlmService()
    llm.register(["echo"], TerminalUI(EchoAdapter()))  # UI 装饰在模型外层
    tools = ToolService()
    tools.register(
        name="echo",
        description="把给定文本原样返回（演示用）",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要回显的文本"}},
            "required": ["text"],
        },
        fn=lambda text: f"echo: {text}",
    )
    return Agent(
        id="echo-demo",
        session=session,
        llm=llm,
        tools=tools,
        model="echo",
        system_prompt="你是 PAgent 的演示 agent。",
        max_steps=8,  # 防跑飞闸（亲手点②会把它改成 1 观察截断）
    )


def main() -> None:
    agent = build_agent()
    print("PAgent echo demo（quit 退出；试试：echo 你好）")
    while True:
        try:
            line = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line or line == "quit":
            break
        agent.send([TextBlock(text=line)])
        print("PAgent> ", end="", flush=True)
        asyncio.run(run_loop(agent))
        print()  # 流式回显后补个换行
        last = agent.session.events[-1]
        if last.type == "turn/end":
            print(f"  [turn{last.data['turn']} 结束，原因: {last.data['reason']}]")
    print("再见。")


if __name__ == "__main__":
    main()
