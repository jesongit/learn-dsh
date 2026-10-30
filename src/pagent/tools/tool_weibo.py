"""fetch_weibo_hot_search —— M3-03：第一个真工具（PAgent 场景正主）。

场景定档（决策记录）：总结微博热搜榜。接口 weibo.com/ajax/side/hotSearch
（非官方 JSON，M2 起真实调用）。

这是 AI 生成的样板（I/O 管线，非核心逻辑）——async def 工具同样被
ToolService 支持（execute 会 await），读懂它，收官亲手点你写一个
自己想要的新工具。
"""

from __future__ import annotations

import httpx

from pagent.tools.registry import tool

_API = "https://weibo.com/ajax/side/hotSearch"
_HEADERS = {"User-Agent": "Mozilla/5.0 (PAgent demo)"}  # 裸 UA 会被拒


@tool(description="抓取微博热搜榜，返回前 N 条热搜词及其热度")
async def fetch_weibo_hot_search(limit: int = 10) -> str:
    async with httpx.AsyncClient(headers=_HEADERS, timeout=10) as client:
        resp = await client.get(_API)
        resp.raise_for_status()
        realtime = resp.json()["data"]["realtime"]

    lines = [
        f"{i}. {item['word']}（热度 {item.get('num', '?')}）"
        for i, item in enumerate(realtime[:limit], start=1)
    ]
    return "\n".join(lines) or "(热搜榜为空)"
