"""M5-01 作业区：委派——子级装配回收 + spawn 工具（测试即规格）。

TODO(R)(S) 骨架在 src/pagent/tool_subagent.py——两条 skip 挂起，逐条解锁
（先 R 后 S），全绿 = 本节完成。
运行：uv run pytest tests/test_subagent.py -v

要点：
- 子级工厂用闭包把 mock llm 注入子级，并**捕获子级 Session**供隔离断言。
- 子级与父级共享 REGISTRY（模块级单表）——子级理论上能再派生；本节用
  max_steps 兜底，显式隔离记待探索。
"""

from __future__ import annotations

import asyncio

import pytest

from pagent.llm.adapter import LlmService
from pagent.core.agent import Agent
from pagent.llm.mock import MockAdapter, text_response
from pagent.core.session import Session
from pagent.tools.registry import ToolService
from pagent.core.types import TextBlock


def _make_factory(sessions: list[Session], reply: str = "子任务完成"):
    """子级工厂：每次调用造全新子级（独立 Session、共享 mock llm），并捕获 Session。"""
    llm = LlmService()
    adapter = MockAdapter([text_response(reply)])
    llm.register(["mock"], adapter)

    def factory() -> Agent:
        session = Session("child")
        sessions.append(session)
        return Agent(id="child-1", session=session, llm=llm,
                     tools=ToolService(), model="mock", max_steps=8)

    return factory



def test_run_subagent_returns_terminal_result():
    """契约：终态语义 = [reason] + 最终回复；子级是独立事件叙事。"""
    from pagent.tools.tool_subagent import run_subagent

    sessions: list[Session] = []
    factory = _make_factory(sessions, reply="子任务完成")

    result = asyncio.run(asyncio.wait_for(run_subagent(factory, "整理数据"), timeout=5))

    assert result == "[completed] 子任务完成"
    child = sessions[0]
    types = [e.type for e in child.events]
    assert "user/message" in types and "assistant/message" in types and "turn/end" in types
    assert types.count("turn/end") == 1  # 跑到终态即停



def test_spawn_via_tool_service():
    """契约：make_spawn_tool 注册后，经 ToolService 全管线可用（async 工具被 execute await）。"""
    from pagent.tools.tool_subagent import make_spawn_tool

    sessions: list[Session] = []
    factory = _make_factory(sessions)
    make_spawn_tool(factory)

    outcome = asyncio.run(
        ToolService().execute("c1", "spawn", {"task": "总结数据"})
    )
    assert not outcome.is_error
    assert "[completed] 子任务完成" in outcome.content[0].text



def test_child_failure_surfaces_as_terminal():
    """契约：子级失败也是终态数据——[error] 回收，父级不炸。"""
    from pagent.tools.tool_subagent import run_subagent

    llm = LlmService()
    llm.register(["mock"], MockAdapter([]))  # 空脚本：子级模型调用必然失败
    sessions: list[Session] = []

    def factory() -> Agent:
        session = Session("child-err")
        sessions.append(session)
        return Agent(id="child-err", session=session, llm=llm,
                     tools=ToolService(), model="mock", max_steps=8)

    result = asyncio.run(asyncio.wait_for(
        run_subagent(factory, "必失败的任务"), timeout=5))
    assert result.startswith("[error]")
