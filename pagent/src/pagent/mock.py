"""MockAdapter：预注册响应的测试替身（stub）—— M1-01 任务，已实现。

对照：deepseek-harness@53d1ef4a74 packages/agent-loop/tests/mock-adapter.ts。

它和真实 adapter 实现**同一个接口**，唯一的区别是：
响应不是算出来的，是按预注册序列回放的。M1 全程它就是你的「模型」。

写完自测：uv run pytest tests/test_mock.py
（收尾状态：5 passed）

**两条注入路径**（防混淆）：
- options 是**方法参数**——每次请求传入的「问题」，替身只记账不阅读；
- script 是**构造函数注入的状态**——预录「答案」队列，跨调用持久，
  被 pop(0) 逐条消耗。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

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
    ToolCallBlock,
    ToolCallDelta,
    UsageChunk,
)


def text_response(text: str) -> list[StreamChunk]:
    """一段纯文本响应的 chunk 序列（fixture 工厂）—— 已实现，当模板读。

    chunk 流的固定节奏：block-start → 逐字符 text-delta → block-end
    → usage → finish(stop)。逐字符吐 delta 是在模拟真实模型的流式输出；
    block-end 携带拼好的完整块，消费方可以偷懒不自己组装。
    """
    chunks: list[StreamChunk] = [
        BlockStart(index=0, block_type="text"),
        *[TextDelta(index=0, text=char) for char in text],
        BlockEnd(index=0, block=TextBlock(text=text)),
        UsageChunk(usage=TokenUsage(input_tokens=10, output_tokens=len(text))),
        Finish(reason="stop"),
    ]
    return chunks


def tool_call_response(
    call_id: str, name: str, args: dict, text: str | None = None
) -> list[StreamChunk]:
    """一次工具调用的 chunk 序列（fixture 工厂）—— 已实现 ✓。

    行为规格（与测试断言一一对应）：

    - 若给了 text：先用 index=0 吐一个完整文本块
      （BlockStart → 一个 TextDelta → BlockEnd），然后 index 加一
    - 工具调用块（用当前的 index）：
      BlockStart(index, "tool-call")
      两个 ToolCallDelta —— arguments 的 JSON 串分两半吐（模拟流式参数），
      第一个带 name，第二个 name=None（身份只说一次）
      BlockEnd(index, ToolCallBlock(id=call_id, name=name,
                                    arguments=json.dumps(args)))
    - 收尾 UsageChunk + Finish —— finish 原因是 "tool-calls"，
      不是 "stop"（loop 就靠这个判断要不要继续转）
    """
    if text is None:
        index = 0
        text_len = 0
        text_chunks = []
    else:
        index = 1
        text_len = len(text)
        text_chunks = text_response(text)[:-2]

    args_str=json.dumps(args)
    mid = len(args_str) // 2
    left = args_str[:mid]
    right = args_str[mid:]
    tool_chunks: list[StreamChunk] = [
        BlockStart(index=index, block_type="tool-call"),
        ToolCallDelta(index=index, id=call_id, name=name, arguments_delta=left),
        ToolCallDelta(index=index, id=call_id, name=None, arguments_delta=right),
        BlockEnd(index=index, block=ToolCallBlock(id=call_id, name=name,arguments=args_str)),
        UsageChunk(usage=TokenUsage(input_tokens=10, output_tokens=text_len + len(args_str))),
        Finish(reason="tool-calls")
    ]
    return text_chunks + tool_chunks
    # raise NotImplementedError("TODO(1)：照上面的要点实现 tool_call_response")


class MockAdapter(LLMAdapter):
    """按预注册序列回放响应的测试替身，并记录收到的每个请求供测试断言。

    stream() 的三条规则（已实现）：
      1. 先把 options 记进 self.requests（loop 发什么请求，测试要能查）
      2. 从 self.script 取走下一条**预录响应**：list.pop(0)；队列空了
         就 raise RuntimeError("MockAdapter: 脚本耗尽")
      3. 依次 yield 这条响应里的每个 chunk

    延伸思考（不用实现，M2 会用）：harness 的脚本还支持 'hang' 条目——
    只吐半个块就挂起，直到被 abort。想想这个怎么写？
    """

    def __init__(
        self,
        script: list[list[StreamChunk] | Callable[[GenerateOptions], list[StreamChunk]]],
    ) -> None:
        """script = **预录响应队列**（fixture 序列）：每个元素是一次完整
        响应（一串 chunks，由 text_response / tool_call_response 生成），
        或者一个**函数条目** `(options) -> chunks`——按请求现场算响应，
        常用于在流式期间制造副作用（如模拟用户插话，见 test_steering_*）。
        loop 每发一次请求，stream() 取走队首的一条；三次请求消费三条响应。
        """
        self.script = list(script)
        self.requests: list[GenerateOptions] = []

    async def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        self.requests.append(options)
        if not self.script:
            raise RuntimeError("MockAdapter: 脚本耗尽")
        entry = self.script.pop(0)
        chunks = entry(options) if callable(entry) else entry
        for chunk in chunks:
            yield chunk