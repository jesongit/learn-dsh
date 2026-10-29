"""DeepSeekAdapter：真实模型适配器 —— M2-01 亲手写任务。

① 语义：把 DeepSeek 的 HTTP/SSE 方言逐段翻译成 M1-01 定下的 StreamChunk 词汇。
   wire format 只活在本文件内——adapter 之外的代码一行不改（M1-01 宪法兑现）。
   对照：deepseek-harness 的 packages/llm/llm-deepseek（分层相同：帧→事件→chunk）。

② ③ 复杂部分（SSE 协议与数据样例）见类 docstring——那是本文件的说明书。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from pagent.adapter import LLMAdapter
from pagent.types import (
    Finish,
    GenerateOptions,
    StreamChunk,
    TextBlock,
    TextDelta,
    ToolCallDelta,
)

API_URL = "https://api.deepseek.com/chat/completions"

# finish_reason（DeepSeek）→ 我们的 FinishReason 枚举（types.py 定义过、M1 一直没启用的两位登场）
_FINISH_MAP = {
    "stop": "stop",
    "tool_calls": "tool-calls",
    "length": "max-tokens",
}

_SSE_PREFIX = "data: "

# ── ③ 样例数据：一条流式响应的 SSE 原文（按真实 wire 采样）──────────────
# 教训（M2-03 集成时发现）：真实流里【每一帧】都带 finish_reason 键，
# 中间帧值为 null，只有末帧有值——判断要用值而非键。样例必须忠实于真实 wire。
SSE_SAMPLE = "\n".join(
    [
        'data: {"choices":[{"delta":{"role":"assistant","content":"你"},"finish_reason":null}]}',
        "",
        'data: {"choices":[{"delta":{"content":"好"},"finish_reason":null}]}',
        "",
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1",'
        '"function":{"name":"echo","arguments":"{\\"text\\": "}}]},"finish_reason":null}]}',
        "",
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"\\"hi\\"}"}}]},"finish_reason":null}]}',
        "",
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "",
        "data: [DONE]",
    ]
)
# 注意两个现实细节（M1-01 mock 的现实原型）：
#   工具参数分两帧到达（'{\"text\": ' + '\"hi\"}'，拼回才是完整 JSON）；
#   id/name 只在第一帧出现，后续帧没有（name 只说一次）。


class DeepSeekAdapter(LLMAdapter):
    """唯一的 wire format 翻译官：GenerateOptions 进，StreamChunk 流出。"""

    def __init__(self, api_key: str, transport: httpx.AsyncTransport | None = None) -> None:
        # transport 供测试注入 httpx.MockTransport（不联网回放预录 SSE）；生产留 None
        self._api_key = api_key
        self._transport = transport

    # ── TODO(A)：请求体 ──────────────────────────────────────────────
    # 语义：GenerateOptions → DeepSeek 请求体（M1 冒烟见过的形状）+ 流式开关。
    # system 单独放一条 system 消息；每条消息的 content 把各 TextBlock 的文本拼接。
    # 伪代码：
    #   messages = [system?] + [{"role": m.role, "content": 拼接文本} for m in options.messages]
    #   返回 {"model": …, "messages": messages, "stream": True}
    def _build_body(self, options: GenerateOptions) -> dict:
        messages = []
        if options.system is not None:
            messages.append({"role": "system", "content": options.system})
        #print(messages)
        for m in options.messages:
            #print(m)
            content = "".join([tb.text for tb in m.content if isinstance(tb, TextBlock)])
            messages.append({"role": m.role, "content": content})
        # print(messages)
        return {"model": options.model, "messages": messages, "stream": True}
        # raise NotImplementedError("TODO(A)")

    # ── TODO(B)：SSE 帧解析（纯函数，测试主力）───────────────────────
    # 语义：SSE 全文 → JSON 事件列表。
    # 规则：逐行扫；空行 / 非 "data: " 开头的行跳过；剥掉 "data: " 前缀后
    #       若是 "[DONE]" 就停止收集；其余 json.loads 追加。
    # 对照样例 SSE_SAMPLE：应产出 5 个 dict（[DONE] 不算）。
    @staticmethod
    def parse_sse(text: str) -> list[dict]:
        res = []
        for line in text.split("\n"):
            if line == f"{_SSE_PREFIX}[DONE]":
                break
            elif line.startswith(_SSE_PREFIX):
                res.append(json.loads(line.removeprefix(_SSE_PREFIX)))
        return res
        # raise NotImplementedError("TODO(B)")

    # ── TODO(C)：事件翻译 ────────────────────────────────────────────
    # 语义：一个 SSE JSON 事件 → 0..n 个 chunk。分支（按序）：
    #   choices 为空            → []（如纯 usage 帧，v0 忽略，M4 再接）
    #   delta 有非空 "content"  → [TextDelta(index=0, text=…)]
    #   delta 有 "tool_calls"   → 每个tc 一个 ToolCallDelta(index=tc["index"],
    #                             id=tc.get("id"), name=tc["function"].get("name"),
    #                             arguments_delta=tc["function"].get("arguments", ""))
    #                             （id/name 只首帧有，get 缺席即 None）
    #   finish_reason 非 None   → [Finish(reason=_FINISH_MAP[...])]
    #   都没有                  → []

    @staticmethod
    def translate_event(event: dict) -> list[StreamChunk]:
        choices = event["choices"]
        if choices == []:
            return []
        finish_reason = choices[0].get("finish_reason")
        if finish_reason is not None:
            return [Finish(_FINISH_MAP[finish_reason])]
        delta: dict = choices[0]["delta"]
        if "content" in delta:
            return [TextDelta(index=0, text=delta["content"])]
        if "tool_calls" in delta:
            return [ToolCallDelta(tc["index"], tc.get("id", ""), tc["function"].get("name", None), 
                                  tc["function"].get("arguments", "")) for tc in delta["tool_calls"]]
        return []
        # raise NotImplementedError("TODO(C)")

    # ── TODO(D)：串装 ────────────────────────────────────────────────
    # 语义：httpx 流式 POST → 逐行剥壳 → 逐帧翻译 → 逐 chunk yield，[DONE] 停。
    # 伪代码：
    #   async with httpx.AsyncClient(transport=self._transport) as client:
    #     async with client.stream("POST", API_URL, headers=鉴权, json=_build_body) as resp:
    #       resp.raise_for_status()
    #       async for line in resp.aiter_lines():
    #         跳过空行 / 非 data: 行；剥 "data: " 前缀；"[DONE]" → return
    #         for chunk in self.translate_event(json.loads(payload)): yield chunk
    # （B 与 D 是同一套规则的两个世界：B 吃全文可测，D 吃增量真流——取舍 M2-02 再收）
    async def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        async with httpx.AsyncClient(transport=self._transport) as client:
            async with client.stream("POST", API_URL, 
                                     headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}, 
                                     json=self._build_body(options)) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    #print(f"|{line}|", isinstance(line, str), line.startswith(_SSE_PREFIX))
                    if line == f"{_SSE_PREFIX}[DONE]":
                        return
                    if line.startswith(_SSE_PREFIX):
                        event = json.loads(line.removeprefix(_SSE_PREFIX))
                        #print("event", event)
                        for chunk in self.translate_event(event):
                            yield chunk
        #raise NotImplementedError("TODO(D)")
