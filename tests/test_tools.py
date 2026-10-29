"""M3-01 作业区：@tool 说明书自动生成 + pydantic 校验管线（测试即规格）。

当前状态：tools.py 里有**参考实现**（AI 生成供学习），四条 @tool 用例已解锁、
应全绿。重写流程：读懂 tools.py 参考实现 → 整段删除 → pytest 变红 →
对照 TODO(P)(Q)(R) 自己重写 → 回到全绿 = 本节完成（重写才是亲手写本体）。
运行：uv run pytest tests/test_tools.py -v

注意两点：
- `from pagent.tools import tool` 写在测试函数体内——你删掉实现后重写期间，
  不会拖垮整个文件的收集（失败只发生在具体用例里）。
- REGISTRY 是模块级共享的：多个用例注册同名工具会互相覆盖、不同名会
  互相可见，所以断言一律按名字取 schema，不假设「注册表里只有它」。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from pagent.tools import REGISTRY, ToolService


def test_schema_generated_from_signature_real():
    """契约：@tool 之后 schemas() 的 parameters 从签名长出来，零手写。"""
    from pagent.tools import tool

    @tool(description="抓取微博热搜榜")
    def fetch_weibo(limit: int = 10) -> list[dict]:
        return []

    schema = next(s for s in ToolService().schemas() if s.name == "fetch_weibo")
    assert schema.description == "抓取微博热搜榜"
    assert schema.parameters["type"] == "object"
    assert schema.parameters["properties"]["limit"]["type"] == "integer"
    assert schema.parameters["properties"]["limit"]["default"] == 10
    assert REGISTRY["fetch_weibo"].fn is fetch_weibo  # 原函数原样返回


def test_happy_path_executes_with_valid_args():
    """契约：合法参数 → 校验通过 → 执行 → 结果 JSON 化进 ToolOutcome。"""
    from pagent.tools import tool

    @tool(description="加法")
    def add(a: int, b: int) -> dict:
        return {"sum": a + b}

    outcome = asyncio.run(ToolService().execute("c1", "add", {"a": 1, "b": 2}))
    assert not outcome.is_error
    assert json.loads(outcome.content[0].text) == {"sum": 3}


def test_type_mismatch_becomes_error_with_field_name():
    """契约：类型不符 → 字段级错误数据回模型（M1 铁律不变，错误质量升级）。"""
    from pagent.tools import tool

    @tool(description="加法")
    def add(a: int, b: int) -> dict:
        return {}

    outcome = asyncio.run(ToolService().execute("c1", "add", {"a": "abc", "b": 2}))
    assert outcome.is_error
    assert "a" in outcome.content[0].text  # 错误消息精确到字段名


def test_missing_required_becomes_error():
    """契约：缺必填参数（无默认值）同样被校验拦下。"""
    from pagent.tools import tool

    @tool(description="加法")
    def add(a: int, b: int) -> dict:
        return {}

    outcome = asyncio.run(ToolService().execute("c1", "add", {"a": 1}))
    assert outcome.is_error
    assert "b" in outcome.content[0].text


def test_m1_register_path_still_works():
    """回归护栏：M1 手写说明书的 register() 不被本次升级破坏（无需解锁）。"""
    tools = ToolService()
    tools.register("echo", "原样返回", {"type": "object"}, lambda **kw: kw.get("text", ""))
    schema = next(s for s in tools.schemas() if s.name == "echo")
    assert schema.parameters == {"type": "object"}
    outcome = asyncio.run(tools.execute("c1", "echo", {"text": "hi"}))
    assert not outcome.is_error
    assert outcome.content[0].text == "hi"


def test_unknown_tool_still_error():
    """回归护栏：未知工具 → is_error（两代注册方式共用的行为，无需解锁）。"""
    outcome = asyncio.run(ToolService().execute("c1", "nope", {}))
    assert outcome.is_error
