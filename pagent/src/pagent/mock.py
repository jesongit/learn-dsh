"""MockAdapter：脚本化的假模型 —— M1-01 亲手写任务。

对照：deepseek-harness@53d1ef4a74 packages/agent-loop/tests/mock-adapter.ts。

它和真实 adapter 实现**同一个接口**，唯一的区别是：
响应不是算出来的，是照脚本念出来的。M1 全程它就是你的「模型」。

写完自测：uv run pytest tests/test_mock.py
（当前应是 1 passed + 3 failed；全写完应是 4 passed）
"""

from __future__ import annotations

import json
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
    ToolCallBlock,
    ToolCallDelta,
    UsageChunk,
)


def text_response(text: str) -> list[StreamChunk]:
    """一段纯文本响应的 chunk 脚本 —— ✅ 已写好，当模板读。

    对照 mock-adapter.ts 的 textResponse()。chunk 流的固定节奏：
    block-start → 逐字符 text-delta → block-end → usage → finish(stop)

    逐字符吐 delta 是在模拟真实模型的流式输出；block-end 携带拼好的
    完整块，消费方可以偷懒不自己组装。
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
    """一次工具调用的 chunk 脚本 —— TODO(1) 亲手实现。

    对照 mock-adapter.ts 的 toolCallResponse()。要点：

    - 若给了 text：先用 index=0 吐一个完整文本块
      （BlockStart → 一个 TextDelta → BlockEnd），然后 index 加一
    - 工具调用块（用当前的 index）：
      BlockStart(index, "tool-call")
      两个 ToolCallDelta —— arguments 的 JSON 串分两半吐（模拟流式参数），
      第一个带 name，第二个 name=None
      BlockEnd(index, ToolCallBlock(id=call_id, name=name,
                                    arguments=json.dumps(args)))
    - 收尾 UsageChunk + Finish —— 注意 finish 原因是 "tool-calls"，
      不是 "stop"（下一节 loop 就靠这个判断要不要继续转）
    """
    raise NotImplementedError("TODO(1)：照上面的要点实现 tool_call_response")


class MockAdapter(LLMAdapter):
    """按脚本逐条响应的假模型，并记录收到的每个请求供测试断言。

    TODO(2)：实现 stream()。三条规则：
      1. 先把 options 记进 self.requests（loop 发什么请求，测试要能查）
      2. 从 self.script 取走下一条脚本：list.pop(0)；取不到就
         raise RuntimeError("MockAdapter: 脚本耗尽")
      3. 依次 yield 脚本里的每个 chunk

    注意：LLMAdapter 接口要求 stream 是 async generator —— 把下面的
    方法改成 async def，并逐个 yield，而不是 return 一个列表。

    延伸思考（不用实现，M2 会用）：harness 的脚本还支持 'hang' 条目——
    只吐半个块就挂起，直到被 abort。想想这个怎么写？
    """

    def __init__(self, script: list[StreamChunk]) -> None:
        self.script = list(script)
        self.requests: list[GenerateOptions] = []

    def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError("TODO(2)：改成 async generator 并实现三条规则")
