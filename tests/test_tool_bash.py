"""M3-02 作业区：结果整形 + bash_run 错误分层（测试即规格）。

全部解锁后的契约清单（实现见 src/pagent/tool_bash.py）。
运行：uv run pytest tests/test_tool_bash.py -v

注意：shell=True 在 Windows 走 cmd.exe、在类 Unix 走 /bin/sh——
用例只依赖两边行为一致的命令（echo / exit N / python）。
"""

from __future__ import annotations

import asyncio

import pytest

def test_render_result_stdout_only():
    """契约：正常输出 → 原文返回，零标记。"""
    from pagent.tools.tool_bash import render_result

    assert render_result("hi\n", "", 0) == "hi\n"


def test_render_result_stderr_section_and_marker():
    """契约：stderr 分节 + 非零退出标记；正文空时从 [stderr] 起头。"""
    from pagent.tools.tool_bash import render_result

    assert render_result("", "boom\n", 1) == "[stderr]\nboom\n[exit code: 1]"


def test_render_result_stdout_then_stderr_both_kept():
    """契约：stdout 与 stderr 同时非空——stdout 打头不丢（拍②扫描补锁的路径）。"""
    from pagent.tools.tool_bash import render_result

    assert render_result("hi\n", "boom\n", 0) == "hi\n[stderr]\nboom\n"


def test_render_result_no_output_sentinel():
    """契约：全空输出 → (no output) 哨兵——空也是信息。"""
    from pagent.tools.tool_bash import render_result

    assert render_result("", "", 0) == "(no output)"



def test_render_result_timed_out_marker():
    """契约：timed_out 与 exit_code 两条独立标记可同时出现，逐行追加。"""
    from pagent.tools.tool_bash import render_result

    assert render_result("part", "", -9, True) == "part\n[timed out]\n[exit code: -9]"



def test_bash_run_normal_output():
    """契约：正常命令 → is_error=False，输出进正文（装饰即注册，经 REGISTRY 走全管线）。"""
    from pagent.tools import tool_bash  # noqa: F401 —— 导入即完成 @tool 登记
    from pagent.tools.registry import ToolService

    outcome = asyncio.run(
        ToolService().execute("c1", "bash_run", {"command": "echo pagent-demo"})
    )
    assert not outcome.is_error
    assert "pagent-demo" in outcome.content[0].text



def test_bash_run_nonzero_exit_is_not_error():
    """契约（本节灵魂）：非零退出是数据不是错误——is_error=False，标记在正文。"""
    from pagent.tools import tool_bash  # noqa: F401
    from pagent.tools.registry import ToolService

    outcome = asyncio.run(ToolService().execute("c1", "bash_run", {"command": "exit 1"}))
    assert not outcome.is_error
    assert "[exit code: 1]" in outcome.content[0].text



def test_bash_run_timeout_is_data():
    """契约：超时被掐也是数据——is_error=False，正文带 [timed out]。"""
    from pagent.tools import tool_bash  # noqa: F401
    from pagent.tools.registry import ToolService

    outcome = asyncio.run(
        ToolService().execute(
            "c1",
            "bash_run",
            {"command": 'python -c "import time; time.sleep(3)"', "timeout_sec": 1},
        )
    )
    assert not outcome.is_error
    assert "[timed out]" in outcome.content[0].text



def test_bash_run_spawn_error_is_error(monkeypatch):
    """契约：spawn 级机制故障 → 异常通道 → execute 兜成 is_error=True。"""
    import subprocess

    from pagent.tools import tool_bash  # noqa: F401
    from pagent.tools.registry import ToolService

    def boom(*args, **kwargs):
        raise OSError("spawn 失败（模拟）")

    monkeypatch.setattr(subprocess, "run", boom)
    outcome = asyncio.run(
        ToolService().execute("c1", "bash_run", {"command": "whatever"})
    )
    assert outcome.is_error
    assert "工具执行出错" in outcome.content[0].text
