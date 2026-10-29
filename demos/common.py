"""demos 共用件：.env 读取、终端回显装饰器、agent 装配（真模型 + 降速）。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from pagent.adapter import LLMAdapter, LlmService
from pagent.agent import Agent
from pagent.deepseek import DeepSeekAdapter
from pagent.session import Session
from pagent.tools import ToolService
from pagent.types import TextBlock, TextDelta

# 每个 chunk 之间的人为停顿（秒）——给 /stop、/steer 留出手速窗口；0 = 火箭模式
STREAM_DELAY = 0.05


def load_env(path: str = ".env") -> None:
    """极简 .env 读取（M6 换正式方案；这里零依赖）。"""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


class TerminalUI(LLMAdapter):
    """终端回显装饰器：包住任何 adapter，流式期间把文本增量打到屏幕。

    seam 可以叠 seam——UI 不改变模型行为，只是"旁听"chunk 流。
    delay：每个 chunk 之间的人为停顿（秒）——给 /stop、/steer 留出手速窗口。
    """

    def __init__(self, inner: LLMAdapter, delay: float = 0.0) -> None:
        self._inner = inner
        self._delay = delay

    async def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        async for chunk in self._inner.stream(options):
            if isinstance(chunk, TextDelta):
                print(chunk.text, end="", flush=True)
            if self._delay:
                await asyncio.sleep(self._delay)
            yield chunk


def build_agent() -> Agent:
    """装配真模型 agent：DeepSeekAdapter + TerminalUI 降速 + 真工具。

    M3-03 起接真工具：@tool 装饰即写全局 REGISTRY，ToolService 读它——
    所以「接线」只是把工具模块 import 进来（导入即注册）。
    """
    from pagent import tool_bash  # noqa: F401 —— 导入即完成 @tool 登记
    from pagent import tool_weibo  # noqa: F401
    load_env()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY：复制 .env.example 为 .env 并填入")

    session = Session("demo")
    llm = LlmService()
    llm.register(
        ["deepseek-chat"],
        TerminalUI(DeepSeekAdapter(api_key), delay=STREAM_DELAY),
    )
    return Agent(
        id="deepseek",
        session=session,
        llm=llm,
        tools=ToolService(),
        model="deepseek-chat",
        system_prompt="你是 PAgent 的演示 agent。",
        max_steps=8,
    )
