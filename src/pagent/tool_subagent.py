"""spawn 工具 —— M5-01：委派 seam 的 Consumer（面向模型的委派入口）。

对照：deepseek-harness packages/subagent（ctx.subagents 委派服务 + tool-subagent）。

子 agent = 同一套零件的第二次装配：新 Session（独立日志）、同款 llm、
max_steps 防跑飞。父级只回收终态（reason + 最终回复）——子级的中间
过程不进父级上下文（委派的上下文经济学）。

已知取舍：REGISTRY 是模块级单表，子级 ToolService() 能看到 spawn 自己
——子级可再派生（递归），靠 max_steps 兜底；显式工具隔离记待探索。
"""

from __future__ import annotations

from collections.abc import Callable

from pagent.agent import Agent
from pagent.loop import run_until_idle
from pagent.tools import tool
from pagent.types import TextBlock


# TODO(R)：子级装配、运行与回收 —— M5-01 核心 ────────────────────────────
# ①语义：给子级工厂（factory: () -> Agent，每次调用造一个全新子级）和任务
#        文本——装配、派发、跑到终态、回收结论。子级是独立事件叙事：
#        自己的 Session / inbox / loop 任务；父级只拿 [reason] + 最终回复。
# ②伪代码：
#   child = factory()
#   child.send([TextBlock(text=task)])
#   await run_until_idle(child)      # 同一个事件循环内等子级跑到空闲
#   reason = 子日志最后一条 turn/end 的 reason（倒扫，同 next_turn_number 手法）
#   final  = 子日志最后一条 assistant/message 的 TextBlock 拼接
#   return f"[{reason}] {final}"
# 注意：本函数必须 async——它在父 loop 的事件循环里被 execute await，
#       另起 asyncio.run 会 RuntimeError（嵌套循环）。
# ③样例：factory 造出的子级（mock）回复「子任务完成」→
#   run_subagent(factory, "总结数据") == "[completed] 子任务完成"
# async def run_subagent(factory: Callable[[], Agent], task: str) -> str: ...


# TODO(S)：@tool 委派工具 —— 面向模型的 Consumer ────────────────────────
# ①语义：闭包住 factory 的 async 工具——装饰即进 REGISTRY，父级模型即可
#        调用。description 是契约的一半：告诉模型何时委派、委派后只有
#        终态结论回来（没有中间过程）。
# ②样例（形状示意）：
#   def make_spawn_tool(factory: Callable[[], Agent]):
#       @tool(description="把独立子任务委派给子 agent，返回其终态结论")
#       async def spawn(task: str) -> str:
#           return await run_subagent(factory, task)
#       return spawn
# def make_spawn_tool(factory: Callable[[], Agent]): ...
