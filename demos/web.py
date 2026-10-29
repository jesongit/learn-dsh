"""demo_web —— M2-04：给 agent 一张 Web 的脸（M2 收官验收载体）。

跑法：  uv run python -m demos.web
浏览器：http://127.0.0.1:8000

架构（第 0 课原则的兑现：UI 是日志的投影）——
  浏览器 ──EventSource──> GET /events（SSE）<──轮询 session.events──> agent
  浏览器 ──fetch POST──> /send /steer /stop ──> agent.send/steer/abort
loop、session、adapter 零改动——Web 只是又一层数据消费者（与 TerminalUI 平级）。

你要写的：TODO(A) /events SSE 端点——fastapi 核心一课（StreamingResponse +
async generator：M2-01 的角色反转，这次我们当服务端）。
页面与命令端点已备好（fastapi 入门四件套见教材 §2）。
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict

import uvicorn
from demos.common import build_agent, load_env
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from pagent.agent import Agent
from pagent.types import TextBlock

# ── 全局 agent：lifespan 启动时创建，全应用共享同一个常驻循环 ────────────
agent: Agent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """fastapi 生命周期：服务启动时把 agent 拉起来，关闭时体面收场。"""
    global agent
    load_env()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY：复制 .env.example 为 .env 并填入")
    agent = build_agent()  # 复用终端 demo 的接线（真模型 + TerminalUI 降速）
    agent.start()
    yield
    agent.abort()


app = FastAPI(lifespan=lifespan)


class Msg(BaseModel):
    """请求体模型——pydantic 的牛刀小试，M3 它就是主角。"""

    text: str


@app.post("/send")
def send(msg: Msg) -> dict:
    agent.send([TextBlock(text=msg.text)])
    return {"ok": True}


@app.post("/steer")
def steer(msg: Msg) -> dict:
    agent.steer([TextBlock(text=msg.text)])
    return {"ok": True}


@app.post("/stop")
async def stop() -> dict:
    """中断当前 turn，并自动复活常驻循环（方案 a 临时补丁）。

    背景：M2-02 的 v0 语义是「abort 即停止循环任务」（Design B）——终端场景
    重开进程即可，Web 场景页面不关，agent 会永久停摆。这里的复活是
    demo 级补丁；正式归还「abort 后 agent 仍存活」的 harness 语义，
    见 M2-04 教材「已知差异」的 b 方案（待探索）。
    """
    agent.abort()

    async def _revive() -> None:
        old = agent._task  # noqa: SLF001 —— demo 补丁，方案 b 归还时收敛
        if old is not None:
            try:
                await old  # 等旧循环体面退场（turn 收场日志要落完）
            except asyncio.CancelledError:
                pass
        agent.start()  # 拉起新的常驻循环

    asyncio.create_task(_revive())
    return {"ok": True}


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse(PAGE)


# ── TODO(A)：SSE 事件流 ── M2-04 亲手写 ─────────────────────────────────
# 语义：把会话日志的「增量」实时推给浏览器。SSE 帧格式：data: <json> + 空行。
# 角色反转：M2-01 我们逐行剥 DeepSeek 的 SSE；现在我们当 SSE 服务端生产帧。
# 伪代码：
#   async def gen():
#       seq = int(request.query_params.get("seq", 0))   # 断线重连从指定位置续播
#       while True:
#           if await request.is_disconnected(): break    # 页面关了就停
#           events = agent.session.events
#           for e in events[seq:]:
#               yield f"data: {json.dumps(asdict(e), ensure_ascii=False)}\n\n"
#           seq = len(events)
#           await asyncio.sleep(0.1)                     # 轮询间隔
#   return StreamingResponse(gen(), media_type="text/event-stream",
#                            headers={"Cache-Control": "no-cache"})
# 端点本身用普通 def 即可（返回的 StreamingResponse 里有 async generator）。
@app.get("/events")
def events(request: Request):
    async def gen():
        seq = int(request.query_params.get("seq", 0))
        while True:
            if await request.is_disconnected():
                break
            events = agent.session.events
            for e in events[seq:]:
                event_data = json.dumps(asdict(e), ensure_ascii=False)
                yield f"data: {event_data}\n\n"
            seq = len(events)
            await asyncio.sleep(0.1)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ── 内嵌页面：官方聊天风格的极简版（HTML/CSS/JS 单字符串，无构建工具）────
PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>PAgent</title>
<style>
  :root { --bg:#f7f7f8; --bubble:#e3f0ff; --line:#e5e5e5; --text:#1a1a1a; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--text); font:15px/1.6 system-ui,"Segoe UI","Microsoft YaHei"; }
  header { position:fixed; top:0; left:0; right:0; height:52px; background:#fff;
           border-bottom:1px solid var(--line); display:flex; align-items:center;
           padding:0 20px; font-weight:600; }
  #chat { max-width:760px; margin:76px auto 90px; padding:0 16px; }
  .row { display:flex; margin:10px 0; }
  .row.user { justify-content:flex-end; }
  .bubble { max-width:78%; padding:10px 14px; border-radius:14px; white-space:pre-wrap; }
  .user .bubble { background:var(--bubble); }
  .assistant .bubble { background:#fff; border:1px solid var(--line); }
  .caret::after { content:"▍"; animation:blink 1s steps(1) infinite; color:#888; }
  @keyframes blink { 50% { opacity:0; } }
  .sys { text-align:center; color:#999; font-size:12px; margin:8px 0; }
  #bar { position:fixed; bottom:0; left:0; right:0; background:#fff; border-top:1px solid var(--line); }
  #barin { max-width:760px; margin:0 auto; display:flex; gap:8px; padding:12px 16px; }
  #inp { flex:1; resize:none; height:44px; padding:10px 12px; border:1px solid var(--line);
         border-radius:10px; font:inherit; outline:none; }
  #inp:focus { border-color:#4d6bfe; }
  button { border:0; border-radius:10px; padding:0 16px; font:inherit; cursor:pointer; }
  #send { background:#4d6bfe; color:#fff; }
  .ghost { background:#f0f0f0; color:#555; }
</style>
</head>
<body>
<header>PAgent · Web</header>
<div id="chat"></div>
<div id="bar"><div id="barin">
  <textarea id="inp" placeholder="输入消息；/stop 中断；/steer 内容 插话"></textarea>
  <button id="send" onclick="onSend()">发送</button>
  <button class="ghost" onclick="onStop()">停止</button>
</div></div>
<script>
const chat = document.getElementById("chat");
const inp  = document.getElementById("inp");
let seq = 0;
let asst = null;          // 当前正在流式输出的助手气泡

function addRow(cls) {
  const row = document.createElement("div");
  row.className = "row " + cls;
  const b = document.createElement("div");
  b.className = "bubble";
  row.appendChild(b);
  chat.appendChild(row);
  window.scrollTo(0, document.body.scrollHeight);
  return b;
}

function onSend() {
  const text = inp.value.trim();
  if (!text) return;
  if (text === "/stop") { fetch("/stop", {method:"POST"}); inp.value = ""; return; }
  if (text.startsWith("/steer ")) {
    const s = text.slice(7);
    fetch("/steer", {method:"POST", headers:{"Content-Type":"application/json"},
                     body: JSON.stringify({text: s})});
    addRow("user").textContent = "[插话] " + s;
    inp.value = ""; return;
  }
  fetch("/send", {method:"POST", headers:{"Content-Type":"application/json"},
                  body: JSON.stringify({text})});
  addRow("user").textContent = text;   // 自己的气泡本地渲染，SSE 里跳过
  inp.value = "";
}
inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } });

function onStop() { fetch("/stop", {method:"POST"}); }

const es = new EventSource("/events?seq=0");
es.onmessage = e => {
  const ev = JSON.parse(e.data);
  if (ev.seq <= seq) return;
  seq = ev.seq;
  const d = ev.data;
  if (ev.type === "assistant/chunk" && d.chunk && d.chunk.text) {
    if (!asst) { asst = addRow("assistant"); asst.classList.add("caret"); }
    asst.textContent += d.chunk.text;
    window.scrollTo(0, document.body.scrollHeight);
  } else if (ev.type === "turn/end") {
    if (asst) asst.classList.remove("caret");
    asst = null;
    const s = document.createElement("div");
    s.className = "sys";
    s.textContent = "turn" + d.turn + " 结束 · " + d.reason;
    chat.appendChild(s);
  }
};
</script>
</body>
</html>"""


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
