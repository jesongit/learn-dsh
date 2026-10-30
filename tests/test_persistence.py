"""M6-01 作业区：会话持久化（测试即规格）。

TODO(T) save、TODO(U) _revive_block/_revive_chunk、TODO(V) load——骨架在
src/pagent/persistence.py。三条 skip 挂起，按 T → U → V 解锁，全绿 = 完成。

要点：
- 覆盖场景手工拼了**全部 12 种词汇表事件**（含六种 chunk、● 字段五连、
  compaction 哨兵）——恢复函数必须吃下词汇表每一行（教材 §7 坑预告）。
- 往返断言**排除 time**：append 会打新时间戳（记账元数据，恢复不必还原），
  所以比较 (type, seq, data) 三元组而非 SessionEvent 整体。
"""

from __future__ import annotations

import json

import pytest

from pagent.core.session import Session
from pagent.core.types import (
    BlockEnd,
    BlockStart,
    Finish,
    TextBlock,
    TextDelta,
    TokenUsage,
    ToolCallBlock,
    ToolCallDelta,
    ToolResultBlock,
    UsageChunk,
)


def _build_rich_session() -> Session:
    """手工拼一份覆盖全部词汇表的事件日志（合成场景，不跑真 loop）。"""
    s = Session("rich")
    s.append("user/message", {"content": [TextBlock(text="帮我查天气")]})
    s.append("turn/start", {"turn": 1, "trigger": {"kind": "message"}})
    s.append("step/start", {"turn": 1, "step": 1})
    # 六种 chunk 各落一条——恢复的 chunk 重建器一条都不能漏
    s.append("assistant/chunk", {"turn": 1, "step": 1, "chunk": BlockStart(index=0, block_type="text")})
    s.append("assistant/chunk", {"turn": 1, "step": 1, "chunk": TextDelta(index=0, text="好的")})
    s.append("assistant/chunk", {"turn": 1, "step": 1,
                                 "chunk": ToolCallDelta(index=1, id="c1", name="bash_run",
                                                        arguments_delta='{"cm')})
    s.append("assistant/chunk", {"turn": 1, "step": 1,
                                 "chunk": BlockEnd(index=1, block=ToolCallBlock(id="c1", name="bash_run",
                                                                                arguments='{"cmd": "ls"}'))})
    s.append("assistant/chunk", {"turn": 1, "step": 1,
                                 "chunk": UsageChunk(usage=TokenUsage(input_tokens=10, output_tokens=5))})
    s.append("assistant/chunk", {"turn": 1, "step": 1, "chunk": Finish(reason="tool-calls")})
    s.append("assistant/message", {"turn": 1, "step": 1,
                                   "content": [ToolCallBlock(id="c1", name="bash_run",
                                                             arguments='{"cmd": "ls"}')]})
    s.append("assistant/usage", {"turn": 1, "step": 1,
                                 "usage": TokenUsage(input_tokens=10, output_tokens=5)})
    s.append("tool/call", {"turn": 1, "step": 1, "call_id": "c1", "name": "bash_run",
                           "arguments": '{"cmd": "ls"}'})
    s.append("tool/result", {"turn": 1, "step": 1, "call_id": "c1",
                             "content": [TextBlock(text="file1")], "is_error": False})
    s.append("steering/message", {"turn": 1, "content": [TextBlock(text="快点")]})
    s.append("context/message", {"content": [TextBlock(text="用户在北京")]})
    s.append("error", {"turn": 1, "step": 1, "message": "演示错误"})
    s.append("step/end", {"turn": 1, "step": 1})
    s.append("compaction/end", {"upto_seq": 5, "summary": "旧叙事摘要"})
    s.append("turn/end", {"turn": 1, "reason": "completed"})
    return s



def test_save_writes_header_then_events(tmp_path):
    """契约：首行 header，其后一行一事件，行数 = 事件数 + 1。"""
    from pagent.persistence import save

    session = _build_rich_session()
    path = str(tmp_path / "session.jsonl")
    save(session, path)

    lines = open(path, encoding="utf-8").read().splitlines()
    assert json.loads(lines[0]) == {"v": 1, "type": "header"}
    assert len(lines) == len(session.events) + 1
    assert json.loads(lines[1])["type"] == "user/message"



def test_revive_block_and_chunk():
    """契约：dict → dataclass，嵌套（BlockEnd.block / ToolResultBlock.content）递归。"""
    from pagent.persistence import _revive_block, _revive_chunk

    block = _revive_block({"type": "tool-result", "tool_call_id": "c1",
                           "content": [{"type": "text", "text": "file1"}], "is_error": True})
    assert block == ToolResultBlock(tool_call_id="c1",
                                    content=[TextBlock(text="file1")], is_error=True)

    chunk = _revive_chunk({"index": 1, "block": {"type": "text", "text": "你好"}})
    assert chunk == BlockEnd(index=1, block=TextBlock(text="你好"))



def test_load_roundtrip_full_vocabulary(tmp_path):
    """契约：save → load 的往返，词汇表全事件无损（time 除外——新时间戳合法）。"""
    from pagent.persistence import load, save

    original = _build_rich_session()
    path = str(tmp_path / "session.jsonl")
    save(original, path)

    restored = load(path)
    assert isinstance(restored, Session)
    a = [(e.type, e.seq, e.data) for e in original.events]
    b = [(e.type, e.seq, e.data) for e in restored.events]
    assert a == b, "往返后事件序列必须逐条相等（time 除外）"



def test_restored_projection_matches_original(tmp_path):
    """契约：恢复后的一切投影照常工作——derive_messages 逐条相等（M6 的验收核心）。"""
    from pagent.persistence import load, save

    original = _build_rich_session()
    path = str(tmp_path / "session.jsonl")
    save(original, path)

    restored = load(path)
    assert restored.derive_messages() == original.derive_messages()
    assert restored.usage_report() == original.usage_report()
