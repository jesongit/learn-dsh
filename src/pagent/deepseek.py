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
    Message,
    StreamChunk,
    TextBlock,
    TextDelta,
    ToolCallBlock,
    ToolCallDelta,
    ToolResultBlock,
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

    # ── TODO(E)(F)：工具 wire format ── M3-03 亲手写（M2-01 遗留主菜）────
    # 背景：options.tools 至今被忽略（模型根本不知道有工具）；且消息翻译只认
    #       TextBlock——历史里的 ToolResultBlock 会被拼成空串（工具结果蒸发）。
    #       本节升级 _build_body（与 TODO(A) 是同一个方法，重构它；纯文本行为
    #       不得变——护栏测试守着）。
    #
    # TODO(E)：说明书随行（热身）
    # ①语义：options.tools 的每份 ToolSchema 直译成 DeepSeek function-calling
    #        形状挂上请求体——模型由此知道能调什么。
    # ②伪代码：tools 非空时 → body["tools"] = 每份 schema →
    #          {"type": "function",
    #           "function": {"name": …, "description": …, "parameters": 原样}}
    # ③样例：ToolSchema("bash_run", "在宿主机 shell…", {"type": "object", …})
    #   → {"type": "function",
    #      "function": {"name": "bash_run", "description": "在宿主机 shell…",
    #                   "parameters": {"type": "object", …}}}
    #
    # TODO(F)：消息翻译升级（主菜）
    # ①语义：三种消息三种走法——
    #        assistant 消息：ToolCallBlock 收集成 tool_calls 数组挂回该消息
    #        （content 仍是 TextBlock 拼接，可以为空串）；
    #        user 消息里的 ToolResultBlock：逐块拆成**独立**的 role:"tool"
    #        消息，tool_call_id 原样回传（模型的对账凭据），
    #        content = 结果内 TextBlock 拼接；
    #        纯 TextBlock 消息走 M2-01 老路。
    #        硬约束：assistant 带 tool_calls 之后必须紧跟每个 id 的 role:"tool"
    #        回复，缺一个 DeepSeek 直接 400——derive_messages 的投影顺序
    #        天然满足（assistant/message 后面就是 tool/result），翻译时别打乱。
    # ②伪代码：
    #   for m in options.messages:
    #       if m.role == "assistant":
    #           tool_calls = [每个 ToolCallBlock →
    #               {"id": b.id, "type": "function",
    #                "function": {"name": b.name, "arguments": b.arguments}}]
    #           挂 {"role": "assistant", "content": Text 拼接,
    #               "tool_calls": tool_calls（非空才带）}
    #       elif m.role == "user":
    #           逐块分流（保持顺序）：
    #               ToolResultBlock → 立即挂 {"role": "tool",
    #                   "tool_call_id": b.tool_call_id,
    #                   "content": b.content 内 Text 拼接}
    #               TextBlock → 累进缓冲；缓冲非空才挂 {"role": "user", …}
    # ③样例：投影 [assistant([ToolCallBlock("c1","bash_run","{\"command\":\"ls\"}")]),
    #          user([ToolResultBlock("c1", [TextBlock("hi\n")], False)])] →
    #   [{"role": "assistant", "content": "",
    #     "tool_calls": [{"id": "c1", "type": "function",
    #                     "function": {"name": "bash_run",
    #                                  "arguments": "{\"command\":\"ls\"}"}}]},
    #    {"role": "tool", "tool_call_id": "c1", "content": "hi\n"}]

    # ── TODO(A)：请求体 ──────────────────────────────────────────────
    # 语义：GenerateOptions → DeepSeek 请求体（M1 冒烟见过的形状）+ 流式开关。
    # system 单独放一条 system 消息；每条消息的 content 把各 TextBlock 的文本拼接。
    # 伪代码：
    #   messages = [system?] + [{"role": m.role, "content": 拼接文本} for m in options.messages]
    #   返回 {"model": …, "messages": messages, "stream": True}
    @staticmethod
    def _render_message(m: Message) -> list[dict]:
        """一条中性 Message → 0..n 条 wire 消息（role:"tool" 使其可能一对多）。"""
        result = []
        if m.role == "assistant":
            # 模型的回复，回挂 回复消息 和 工具调用
            content = ""
            tool_calls = []
            for block in m.content:
                if isinstance(block, TextBlock):
                    content += block.text
                elif isinstance(block, ToolCallBlock):
                    tool_calls.append({"id": block.id, "type": "function", "function":{
                        "name": block.name, "arguments": block.arguments
                    }})
            if tool_calls:
                result = [{"role": m.role, "content": content, "tool_calls": tool_calls}]
            else:
                result = [{"role": m.role, "content": content}]
        elif m.role == "user":
            # user 消息包含了用户的提示词和工具的 return
            content = ""
            for block in m.content:
                if isinstance(block, TextBlock):
                    content += block.text
                elif isinstance(block, ToolResultBlock):
                    if content != "":
                        result.append({"role": "user", "content": content})
                        content = ""
                    block_content = "".join([bm.text for bm in block.content if isinstance(bm, TextBlock)])
                    result.append({"role": "tool", "tool_call_id": block.tool_call_id, "content": block_content})
            if content != "":
                result.append({"role": "user", "content": content})
        return result


    def _build_body(self, options: GenerateOptions) -> dict:
        messages = []
        if options.system is not None:
            messages.append({"role": "system", "content": options.system})
        for m in options.messages:
            messages.extend(DeepSeekAdapter._render_message(m))
        body = {"model": options.model, "messages": messages, "stream": True}

        if options.tools:
            body["tools"] = [{"type": "function", "function": {
                "name": tool.name, "description": tool.description, "parameters": tool.parameters
            }} for tool in options.tools]

        return body

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
