"""agent loop —— M1-02 亲手写任务：agent 的心脏。

对照：deepseek-harness@53d1ef4a74 packages/agent-loop/src/loop.ts（205 行）。

harness 原版是「永续循环：空闲时挂起等新消息」。v0 简化（记入教材）：
- 排空即返回，不挂起等待（等待要 asyncio.Future，M2 与中断一起讲）；
- 无 steering（M1-03）、无实时 agent/* 事件（M3 事件总线）、
  turn/end 原因恒为 "completed"（错误路径 M1-03/M2）。

结构地图（写之前先背下来）：

    run_loop:  只要 inbox 还有排队的消息 → 开新 turn（连续排队 = 连续 turn）
    run_turn:  领消息落日志 → turn/start → step 循环 → turn/end
    一个 step: 组装请求 → 流式请求模型（chunk 逐个落日志）→ assistant/message
               → 执行 tool-call 并回填 tool/result → step/end → 方向盘决策
"""

from __future__ import annotations

import json
from pagent.agent import Agent
from pagent.assembler import BlockAssembler
from pagent.types import GenerateOptions, ToolCallBlock


async def run_loop(agent: Agent) -> None:
    """驱动 agent：排空 inbox 里所有排队的输入（每个 turn 一批）。

    TODO(1)：一行循环——while agent.inbox.has_queued: await run_turn(agent)
    """
    while agent.inbox.has_queued:
        await run_turn(agent)
    # raise NotImplementedError("TODO(1)")


async def run_turn(agent: Agent) -> None:
    """一个轮次：领取输入 → step 循环 → 关轮。按 TODO(2)~(10) 逐段实现。"""
    session = agent.session
    turn = session.next_turn_number()
    #raise NotImplementedError("M1-02：删掉本行，按 TODO(2)~(10) 实现 run_turn")

    
    # TODO(2)：从 agent.inbox 整批领取排队的消息（drain_queued），
    #          逐条落日志：session.append("user/message", {"content": 消息.content})
    for msg in agent.inbox.drain_queued():
        session.append("user/message", {"content": msg.content})

    # TODO(3)：开轮：session.append("turn/start", {"turn": turn, "trigger": {"kind": "message"}})
    session.append("turn/start", {"turn": turn, "trigger": {"kind": "message"}})

    step = 0
    had_tool_calls = False
    while True:
        step += 1

        # TODO(4)：step 开张：session.append("step/start", {"turn": turn, "step": step})
        session.append("step/start", {"turn": turn, "step": step})

        # ---- 组装请求：模型历史是日志的投影，不是你手里攒的列表 ----
        request = GenerateOptions(
            model=agent.model,
            messages=session.derive_messages(),
            system=agent.system_prompt,
            tools=agent.tools.schemas() or None,
        )

        # ---- 流式请求模型 ----
        assembler = BlockAssembler() # 组装器，组装返回的 chunks
        # TODO(5)：async for chunk in agent.llm.stream(request):
        #     先 session.append("assistant/chunk", {"turn": turn, "step": step, "chunk": chunk})
        #     再 assembler.push(chunk)
        #     （顺序别反：先记账再组装——「模型可见即已记录」）
        async for chunk in agent.llm.stream(request):
            session.append("assistant/chunk", {"turn": turn, "step": step, "chunk": chunk})
            assembler.push(chunk)

        # TODO(6)：assistant = assembler.message()；
        #          session.append("assistant/message", {"turn": turn, "step": step,
        #                                               "content": assistant.content})
        assistant = assembler.message()
        session.append("assistant/message", {"turn": turn, "step": step, "content": assistant.content})

        # ---- 执行本 step 的全部工具调用（TODO(6) 完成后 assistant 才存在）----
        tool_calls = [
            block for block in assistant.content if isinstance(block, ToolCallBlock)
        ]
        for call in tool_calls:
            # TODO(7)：三步——
            #   a. session.append("tool/call", {"turn": turn, "step": step,
            #                       "call_id": call.id, "name": call.name,
            #                       "arguments": call.arguments})
            #   b. 解析参数：json.loads(call.arguments)，失败时回退原始字符串
            #      （记得 import json）
            #   c. outcome = await agent.tools.execute(call.id, call.name, parsed)
            #      session.append("tool/result", {"turn": turn, "step": step,
            #                          "call_id": outcome.call_id,
            #                          "content": outcome.content,
            #                          "is_error": outcome.is_error})
            # ...  # 占位（Ellipsis）：实现 TODO(7) 时删掉
            session.append("tool/call", {"turn": turn, "step": step, "call_id": call.id, "name": call.name, "arguments": call.arguments})
            try:
                parsed = json.loads(call.arguments)     # 正常路：解析成 dict
            except json.JSONDecodeError:                # json 解析失败抛这个异常（ValueError 的子类）
                parsed = call.arguments                 # 降级：把模型写的原始字符串当参数往下传
            outcome = await agent.tools.execute(call.id, call.name, parsed)
            session.append("tool/result", {"turn": turn, "step": step, "call_id": outcome.call_id, "content": outcome.content, "is_error": outcome.is_error})

        # TODO(8)：step 收工：session.append("step/end", {"turn": turn, "step": step})
        session.append("step/end", {"turn": turn, "step": step})

        # TODO(9)：方向盘——had_tool_calls = len(tool_calls) > 0；
        #          没调工具（模型不欠工作了）就 break，否则继续下一个 step
        had_tool_calls = len(tool_calls) > 0
        if not had_tool_calls:
            break

    # TODO(10)：关轮：session.append("turn/end", {"turn": turn, "reason": "completed"})
    session.append("turn/end", {"turn": turn, "reason": "completed"})
