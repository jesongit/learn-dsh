"""M1 收尾冒烟测试：向 DeepSeek API 发一个真实（非流式）请求。

用途：验证我们设计的 adapter 接口形状能装下真实模型的响应——
仅此而已，流式（SSE）留给 M2。

前置：根目录 `.env` 里有 DEEPSEEK_API_KEY（模板见 .env.example）。
跑法：uv run python demo_smoke.py

实现说明：用标准库 urllib 直连（httpx 到 M2 才引入）；响应被手工拆成
StreamChunk 塞进同一个接口形状——先看数据长什么样，M2 再正式写适配器。
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import AsyncIterator

from pagent.adapter import LLMAdapter
from pagent.types import (
    BlockEnd,
    BlockStart,
    Finish,
    GenerateOptions,
    StreamChunk,
    TextBlock,
    TextDelta,
    TokenUsage,
    UsageChunk,
)

API_URL = "https://api.deepseek.com/chat/completions"


def load_env(path: str = ".env") -> None:
    """极简 .env 读取（M2 会换成正式方案；这里零依赖）。"""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


class DeepSeekSmokeAdapter(LLMAdapter):
    """非流式适配器：一个 HTTP 请求，把完整响应拆成 chunk 流。

    关键观察：真实 wire format 只活在这个类内部——
    messages 里塞 ContentBlock、出来时拆 StreamChunk，接口形状不变。
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        body = {
            "model": options.model,
            "messages": (
                ([{"role": "system", "content": options.system}] if options.system else [])
                + [
                    {
                        "role": m.role,
                        "content": "".join(
                            b.text for b in m.content if hasattr(b, "text")
                        ),
                    }
                    for m in options.messages
                ]
            ),
        }
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read())

        text = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
        yield BlockStart(index=0, block_type="text")
        yield TextDelta(index=0, text=text)
        yield BlockEnd(index=0, block=TextBlock(text=text))
        yield UsageChunk(
            usage=TokenUsage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            )
        )
        yield Finish(reason="stop")


def main() -> None:
    load_env()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY：复制 .env.example 为 .env 并填入 key")

    options = GenerateOptions(
        model="deepseek-chat",
        messages=[Message(role="user", content=[TextBlock(text="用一句话介绍你自己")])],
        system="回答保持一句话以内。",
    )
    adapter = DeepSeekSmokeAdapter(api_key)

    import asyncio

    async def run() -> None:
        print("DeepSeek> ", end="", flush=True)
        async for chunk in adapter.stream(options):
            if isinstance(chunk, TextDelta):
                print(chunk.text, end="", flush=True)
            elif isinstance(chunk, UsageChunk):
                print(
                    f"\n[token 用量] 输入 {chunk.usage.input_tokens} / "
                    f"输出 {chunk.usage.output_tokens}"
                )

    asyncio.run(run())
    print("冒烟通过：接口形状装下了真实模型 ✓")


if __name__ == "__main__":
    main()
