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


# ── TODO(T)：保存 —— M6-01 热身 ──────────────────────────────────────────
# ①语义：首行写版本 header，其后每行 json.dumps(asdict(event))——M3-01 的
#        asdict 老朋友负责把 ● 字段（dataclass）转净。编码显式 utf-8
#        （M4-01 疑点 Q7 的兑现：文件是编码未知的消费者）。
# ②伪代码：
#   with open(path, "w", encoding="utf-8") as f:
#       f.write(json.dumps(_HEADER, ensure_ascii=False) + "\n")
#       对每个事件：f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
# def save(session: Session, path: str) -> None: ...


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
