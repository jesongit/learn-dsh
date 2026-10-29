"""bash_run 工具 —— M3-02：harness「tool-bash」的极简对镜。

对照：deepseek-harness@8b5a3ef730 packages/tool-bash/src/index.ts（renderResult、
validateBashArgs）与 docs/tool-execution-pipeline.zh.md（瀑布全景，刻意不复刻）。

两个核心概念（教材 M3-02）：
- 错误分层：is_error 只给机制错误（spawn 失败——让它炸出去，execute 的既有
  管线兜住）；非零退出、stderr、超时全是**正文数据**，由模型自行决策。
- 结果整形：工具结果的第一读者是模型——整形函数是纯函数、永不抛错。
"""

from __future__ import annotations

import subprocess

from pagent.tools import tool


# ── M3-02 亲手写区 ── 按 TODO(S) → (T) 顺序 ──────────────────────────────

# TODO(S)：结果整形 —— 纯函数，永不抛错（本节主菜之一）
# ①语义：把一次命令运行的四样事实（stdout / stderr / exit_code / 是否超时）
#        拼成一段模型一次读懂的文本。规则（照 harness renderResult 抄语义）：
#        stdout 打头；stderr 非空则另起 [stderr] 分节（其前补一个换行，
#        body 已以换行结尾则不重复补）；stdout 与 stderr 全空 → 哨兵
#        "(no output)"；末尾状态标记逐行追加——timed_out 为 True 加
#        "[timed out]"，exit_code != 0 加 "[exit code: N]"，两条独立判断、
#        可同时出现。标记前 body 末尾没换行则补一个。
# ②伪代码：
#   body = stdout
#   if stderr: 补换行(按需) → body += "[stderr]\n" + stderr
#   if body 为空: body = "(no output)"
#   markers = []          # timed_out 与 exit_code 独立判断，都可入列
#   if markers: 补换行(按需) → body += "\n".join(markers)
#   return body
# ③样例：
#   render_result("hi\n", "", 0)            → "hi\n"
#   render_result("", "boom\n", 1)          → "[stderr]\nboom\n[exit code: 1]"
#   render_result("", "", 0)                → "(no output)"
#   render_result("part", "", -9, True)     → "part\n[timed out]\n[exit code: -9]"
# def render_result(stdout: str, stderr: str, exit_code: int,
#                   timed_out: bool = False) -> str: ...

def render_result(stdout: str, stderr: str, exit_code: int, timed_out: bool = False) -> str:
    # 把bash结果拼成字符串
    body = stdout
    if stderr:
        nn = "" if not body or body.endswith("\n") else "\n"
        body += f"{nn}[stderr]\n{stderr}"
    if not body:
        body = "(no output)"
        
    markers = []
    if timed_out:
        markers.append(f"[timed out]")
    if exit_code != 0:
        markers.append(f"[exit code: {exit_code}]")
    if markers:
      nn = "" if body.endswith("\n") else "\n"
      return body + nn + "\n".join(markers)
    return body

# TODO(T)：bash_run 工具 —— subprocess 执行 + 错误分层（本节主菜之二）
# ①语义：@tool 注册（M3-01 产物第一次接真活）；subprocess.run(command,
#        shell=True, capture_output=True, text=True, timeout=timeout_sec)。
#        分层判决（对照教材 Q：哪层算 error）：
#        - TimeoutExpired → 自己抓住，转成 timed_out=True 走 render_result
#          正文（is_error=False！超时是数据——「调用」本身没失败）；
#        - OSError（spawn 级机制故障）→ 不抓，让它炸出去——execute 的
#          既有管线会兜住并转成 is_error 结果（机制错误走异常通道）；
#        - 跑完（exit 几都算跑完）→ render_result 整形后 return（is_error=False）。
# ②伪代码：
#   try:
#       proc = subprocess.run(..., timeout=timeout_sec)
#   except subprocess.TimeoutExpired:
#       return render_result("", "", 0, timed_out=True)
#   return render_result(proc.stdout, proc.stderr, proc.returncode)
# ③样例（在 cmd / bash 都成立的行为）：
#   bash_run("echo hi")   → "hi"（is_error=False）
#   bash_run("exit 1")    → "[exit code: 1]"（is_error=False！本节灵魂）
#   bash_run("sleep 99", timeout_sec=1) → 含 "[timed out]"
# @tool(description="在宿主机 shell 里执行一条命令，返回 stdout/stderr/退出码")
# def bash_run(command: str, timeout_sec: int = 30) -> str: ...

@tool(description="在宿主机 shell 里执行一条命令，返回 stdout/stderr/退出码")
def bash_run(command: str, timeout_sec: int = 30) -> str:
    try:
      proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return render_result("", "", 0, timed_out=True)
    return render_result(proc.stdout, proc.stderr, proc.returncode)