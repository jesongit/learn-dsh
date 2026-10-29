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

import asyncio
import json
from pagent.agent import Agent
from pagent.assembler import BlockAssembler
from pagent.types import GenerateOptions, ToolCallBlock


async def run_loop(agent: Agent) -> None:
    """驱动 agent：常驻任务——挂起等输入，来一个 turn 跑一个 turn。"""
    # ── TODO(E)：永续化 ── M2-02 亲手写 ─────────────────────────────
    # 语义：归还 v0 让渡的「挂起」——没输入时挂起（不占 CPU），来输入跑 turn。
    # 伪代码：
    #   while True:
    #     try: await agent.inbox.wait_for_queued()   # 挂起等输入
    #     except asyncio.CancelledError: return      # 空闲时被 abort：无 turn 可收，下班
    #     try: await run_turn(agent)
    #     except asyncio.CancelledError: return      # turn 已在 run_turn 内收场(aborted)，任务到此为止
    
    # while agent.inbox.has_queued:
    #     await run_turn(agent)
    while True:
        try:
            await agent.inbox.wait_for_queued()
            await run_turn(agent)
        except asyncio.CancelledError:
            return


async def run_until_idle(agent: Agent, timeout: float = 10.0) -> None:
    """测试助手：启动永续循环，跑完当前积压输入后自动停止。

    run_loop 永续化后不再返回；旧式「排空即返回」的测试语义由本助手承接——
    轮询到「inbox 空 且 无 turn 在跑」即视为空闲，收工取消任务。
    """
    task = asyncio.create_task(run_loop(agent))

    async def wait_idle() -> None:
        while agent.inbox.has_queued or agent.running:
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(wait_idle(), timeout=timeout)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def run_turn(agent: Agent) -> None:
    """一个轮次：领取输入 → step 循环 → 关轮。按 TODO(2)~(10) 逐段实现。"""
    session = agent.session
    turn = session.next_turn_number()

    # TODO(G)：标记运行中——agent.running = True（steer() 靠它分通道）；
    #          并在 run_turn 返回前（turn/end 之后）置回 False
    #raise NotImplementedError("M1-02：删掉本行，按 TODO(2)~(10) 实现 run_turn")
    agent.running = True

    
    # TODO(2)：从 agent.inbox 整批领取排队的消息（drain_queued），
    #          逐条落日志：session.append("user/message", {"content": 消息.content})
    for msg in agent.inbox.drain_queued():
        session.append("user/message", {"content": msg.content})

    # TODO(3)：开轮：session.append("turn/start", {"turn": turn, "trigger": {"kind": "message"}})
    session.append("turn/start", {"turn": turn, "trigger": {"kind": "message"}})

    step = 0
    tool_calls = []
    had_tool_calls = False
    error = None
    reason = "completed"
    while True:
        step += 1

        # TODO(4)：step 开张：session.append("step/start", {"turn": turn, "step": step})
        session.append("step/start", {"turn": turn, "step": step})

        # TODO(J)：模型错误路径（harness 场景 14）。伪代码：
        #   while 前: error = None; had_tool_calls = False
        #   try: <组装请求→流式→工具往返，had_tool_calls 在 try 内算>
        #   except Exception as e: error = str(e)
        #   排插话 + step/end 照旧（错误时日志叙事也要完整）
        #   if error: 落 "error" 事件 → break
        #   turn/end reason ← error 有则 "error"

        try:
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
        # ── TODO(F)：中断收场 ── M2-02 亲手写 ───────────────────────
        # 语义：abort() 的 cancel 会在某个 await 点炸出 CancelledError——
        #       它继承 BaseException，下面的 except Exception 接不住，要单独接。
        # 伪代码：
        #   while 前: aborted = False
        #   在 except Exception 之前加：except asyncio.CancelledError: aborted = True
        #   （收场叙事照旧：排插话、step/end 照落；中止不是事故，不落 error 事件）
        #   reason 若 aborted → "aborted"（优先级：error > aborted > max-steps > completed）
        #   turn/end 与 agent.running = False 之后：raise   # 把取消抛回 run_loop 收尾
        except Exception as e:
            error = str(e)
            # print(error)
            reason = "error"
        except asyncio.CancelledError:
            reason = "aborted"

        # TODO(H)：step 之间消费插话（对照 harness：先排插话、再记 step/end、
        #          最后做方向盘决策，顺序别乱）——
        #   steered_msgs = agent.inbox.drain_steering()
        #   逐条落日志：session.append("steering/message",
        #                            {"turn": turn, "content": m.content})
        #   steered = len(steered_msgs) > 0
        steered_msgs = agent.inbox.drain_steering()
        for msg in steered_msgs:
            session.append("steering/message", {"turn": turn, "content": msg.content})

        # TODO(8)：step 收工：session.append("step/end", {"turn": turn, "step": step})
        session.append("step/end", {"turn": turn, "step": step})

        if error is not None:
            # 报错了，先关闭步骤，记录日志，退出步骤，等模型重新决策
            session.append("error", {"turn": turn, "step": step, "message": error})
            break

        # TODO(9)：方向盘——had_tool_calls = len(tool_calls) > 0；
        #          没调工具（模型不欠工作了）就 break，否则继续下一个 step
        # TODO(I)：方向盘升级——插话也算「欠模型一次请求」：
        #          had_tool_calls or steered 任一为真就继续（steered 来自 TODO(H)）
        had_tool_calls = len(tool_calls) > 0
        if not had_tool_calls and len(steered_msgs) == 0:
            break

        # TODO(K)：max_steps 截断（防跑飞；agent.max_steps 构造传入）。伪代码：
        #   while 前: truncated = False
        #   此处（判定继续之后）: 若 step 已达 agent.max_steps → truncated=True → break
        #   turn/end reason 三态: error > max-steps > completed
        if agent.max_steps is not None and step >= agent.max_steps:
            reason = "max-steps"
            break

    # TODO(10)：关轮：session.append("turn/end", {"turn": turn, "reason": "completed"})
    session.append("turn/end", {"turn": turn, "reason": reason})
    agent.running = False
    if reason == "aborted":
        raise asyncio.CancelledError