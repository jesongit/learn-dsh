"""会话持久化 —— M6-01：日志离开进程（保存 / 恢复）。

对照：deepseek-harness docs/subsystems/persistence.zh.md（JSONL provider、
session/flush 检查点、崩溃恢复）。

格式：JSONL——首行 header {"v": 1, "type": "header"}，其后一行一个事件
（asdict 纯 JSON）。文件与日志同为 append-only：崩溃最多丢最后一行，
前面的行永远完好。

核心认知：序列化边界是**双向**的——出（asdict）容易，进（按类型重建）
才是主菜：投影访问的是 dataclass 属性（usage.input_tokens），读回来的
dict 必须重建为词汇表类型。session.py 的事件词汇表就是字段清单。
"""

from __future__ import annotations

from dataclasses import asdict
import json

from pagent.core.session import Session
from pagent.core.types import (
    BlockEnd,
    BlockStart,
    ContentBlock,
    Finish,
    StreamChunk,
    TextBlock,
    TextDelta,
    TokenUsage,
    ToolCallBlock,
    ToolCallDelta,
    ToolResultBlock,
    UsageChunk,
)

_HEADER = {"v": 1, "type": "header"}

# 五类叙事事件（进投影、占预算）——save 打块标签、load 重建块的共用清单
_CONTENT_EVENTS = {"user/message", "assistant/message", "tool/result",
                   "steering/message", "context/message"}


# ── TODO(T)：保存 —— M6-01 热身 ──────────────────────────────────────────
# ①语义：首行写版本 header，其后每行一个事件的纯 JSON。**content 块必须
#        打类型标签**：asdict 不认 ClassVar（M3-01 验证过），裸 asdict 的块
#        没有 "type" 键，恢复时按 type 分派就会 KeyError——所以五类 content
#        事件的 data["content"] 要用 _dump_block 重写（type 用 b.type 补上，
#        tool-result 递归）；chunk 事件不动（_revive_chunk 按特征键分派，
#        不依赖标签）。编码显式 utf-8（M4-01 疑点 Q7 的兑现）。
# ②伪代码：
#   with open(path, "w", encoding="utf-8") as f:
#       f.write(json.dumps(_HEADER, ensure_ascii=False) + "\n")
#       对每个事件：
#           data = asdict(event)["data"]   # ← 只取 data；asdict 全量会双层嵌套信封
#           if event.type in _CONTENT_EVENTS:
#               data["content"] = [_dump_block(b) for b in event.data["content"]]
#           elif event.type == "assistant/chunk":
#               data["chunk"] = _dump_chunk(event.data["chunk"])  # BlockEnd 内嵌块同样要标签
#           f.write(json.dumps({"type": …, "seq": …, "time": …, "data": data}, …))
# def _dump_block(b: ContentBlock) -> dict: ...
# def _dump_chunk(c: StreamChunk) -> dict: ...
# def save(session: Session, path: str) -> None: ...
def _dump_block(b: ContentBlock) -> dict:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    elif isinstance(b, ToolCallBlock):
        return {"type": "tool-call", "id": b.id, "name": b.name, "arguments": b.arguments}
    elif isinstance(b, ToolResultBlock):
        blocks = [_dump_block(bb) for bb in b.content]
        return {"type": "tool-result", "tool_call_id": b.tool_call_id, "content": blocks, "is_error": b.is_error}


def _dump_chunk(c: StreamChunk) -> dict:
    d = asdict(c)
    if isinstance(c, BlockEnd):
        d["block"] = _dump_block(c.block)   # asdict 会剥掉内嵌块的 ClassVar 标签——补回
    return d


def save(session: Session, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(_HEADER, ensure_ascii=False) + "\n")
        for event in session.events:
            data = asdict(event)["data"]    # ← 只取 data；asdict 全量会把信封双层嵌套
            if event.type in _CONTENT_EVENTS:
                data["content"] = [_dump_block(b) for b in event.data["content"]]
            elif event.type == "assistant/chunk":
                data["chunk"] = _dump_chunk(event.data["chunk"])
            f.write(json.dumps({"type": event.type, "seq": event.seq,
                                "time": event.time, "data": data}, ensure_ascii=False) + "\n")


# ── TODO(U)：按类型重建 —— 恢复方向的主菜 ────────────────────────────────
# ①语义：词汇表的 ● 字段都要从 dict 变回 dataclass。两个重建器：
#   _revive_block：content 块按 b["type"] 分派；tool-result 的 content 是
#                  块列表 → 递归（和 asdict 是同一棵树，方向相反）。
#   _revive_chunk：六种 StreamChunk 按特征键分派（asdict 后各 kind 的键不同）：
#       有 "block_type" → BlockStart        有 "text" → TextDelta
#       有 "id" → ToolCallDelta             有 "block" → BlockEnd（递归 U）
#       有 "usage" → UsageChunk（重建 TokenUsage）
#       有 "reason" → Finish
# ②样例：
#   {"type": "text", "text": "你好"}            → TextBlock(text="你好")
#   {"index": 0, "text": "你"}                  → TextDelta(index=0, text="你")
#   {"usage": {"input_tokens": 10, "output_tokens": 2}}
#                                               → UsageChunk(usage=TokenUsage(10, 2))
# def _revive_block(b: dict) -> ContentBlock: ...
# def _revive_chunk(c: dict) -> StreamChunk: ...

def _revive_block(b: dict) -> ContentBlock:
    if b["type"] == "text":
        return TextBlock(text=b["text"])
    elif b["type"] == "tool-call":
        return ToolCallBlock(id=b["id"], name=b["name"], arguments=b["arguments"])
    elif b["type"] == "tool-result":
        blocks = [_revive_block(bb) for bb in b["content"]]
        return ToolResultBlock(content=blocks, tool_call_id=b["tool_call_id"], is_error=b["is_error"])

def _revive_chunk(c: dict) -> StreamChunk:
    if "block_type" in c:
        return BlockStart(index=c["index"], block_type=c["block_type"])
    elif "text" in c:
        return TextDelta(index=c["index"], text=c["text"])
    elif "id" in c:
        return ToolCallDelta(index=c["index"], id=c["id"], name=c["name"], arguments_delta=c["arguments_delta"])
    elif "block" in c:
        block = _revive_block(c["block"])
        return BlockEnd(block=block, index=c["index"])
    elif "usage" in c:
        usage = TokenUsage(input_tokens=c["usage"]["input_tokens"], 
                           output_tokens=c["usage"]["output_tokens"])
        return UsageChunk(usage=usage)
    elif "reason" in c:
        return Finish(reason=c["reason"])


# ── TODO(V)：恢复 —— 组装 ────────────────────────────────────────────────
# ①语义：读文件 → 首行校验 header（v ≠ 1 或缺 header → ValueError，防把
#        别的文件喂进来）→ 其后每行 json.loads → data 按 type 重建：
#        ● 字段走 _revive_block / _revive_chunk / TokenUsage(**…)，
#        其余字段原样 → session.append(type, data)。
# ③注意：append 自动重排 seq（顺序读取所以与落盘一致）；time 是新时间戳
#        （记账元数据，恢复后不必还原）。
# ②伪代码：
#   session = Session(名字)
#   逐行读：第一行校验 json.loads(line) == _HEADER（v 或 type 不符 → ValueError）
#   其后行：raw = json.loads(line)；data = raw["data"]
#       if type 在五类 content 事件里: data["content"] = [_revive_block(b) …]
#       elif type == "assistant/chunk": data["chunk"] = _revive_chunk(…)
#       elif type == "assistant/usage": data["usage"] = TokenUsage(**data["usage"])
#       session.append(raw["type"], data)
#   return session
# def load(path: str) -> Session: ...

def load(path: str) -> Session:
    session = Session("restored")
    with open(path, "r", encoding="utf-8") as f:
        header_line = f.readline()
        header = json.loads(header_line)
        if header != _HEADER:
            raise ValueError(f"Invalid header: {header}")
        for line in f:
            raw = json.loads(line)
            event_type = raw["type"]
            data = raw["data"]
            if event_type in _CONTENT_EVENTS:
                data["content"] = [_revive_block(b) for b in data["content"]]
            elif event_type == "assistant/chunk":
                data["chunk"] = _revive_chunk(data["chunk"])
            elif event_type == "assistant/usage":
                data["usage"] = TokenUsage(input_tokens=data["usage"]["input_tokens"], output_tokens=data["usage"]["output_tokens"])
            session.append(event_type, data)
    return session