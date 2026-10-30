"""会话：只追加的事件日志 —— 单一事实来源。

对照：deepseek-harness@53d1ef4a74 packages/session/src/index.ts。

两条铁律（来自 harness 的架构文档）：
- **模型可见即已记录**：凡是进过模型上下文的东西，必定能从这份日志重建。
- **模型历史是投影**：derive_messages() 从日志推导消息列表，日志之外
  不存在第二份真相。assistant/chunk 落日志但**不**投影——它是回放/UI 数据，
  组装完的 assistant/message 才是历史。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pagent.types import ContentBlock, Message, TextBlock, ToolResultBlock


@dataclass(frozen=True)
class SessionEvent:
    """日志中的一条不可变事实。"""

    type: str
    seq: int
    time: int  # 毫秒级时间戳
    data: dict


def _render_tagged(tag: str, content: list[ContentBlock]) -> list[ContentBlock]:
    """把注入类消息渲染成带信封的合成 user 消息（system-reminder 模式）。

    对照 harness 的 renderTagged()：模型靠信封区分「真用户说话」和
    「系统注入的上下文」。M1-03 的 steering 会用到。
    """
    return [TextBlock(text=f"<{tag}>"), *content, TextBlock(text=f"</{tag}>")]


class Session:
    """一个会话的事件日志。append 永远成功、永不阻塞——热路径不做 I/O。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self._events: list[SessionEvent] = []

    @property
    def events(self) -> list[SessionEvent]:
        return self._events

    # ── 事件词汇表：全仓库所有 append 的调用形态（新增事件先在此登记）────
    # 写入方只有两处：loop.run_turn（一个 turn 的完整叙事）与 agent.inject。
    # 按 turn 生命周期排列。seq / time 由 append 自动补齐，下表只列 data。
    # 「●」= 该字段装 dataclass 对象（进程内数据，跨进程边界——如 Web SSE
    # 序列化——必须先转纯 JSON）；未标者均为 JSON 原生类型（int/str/bool/dict）。
    #
    #   type               data 字段
    #   ─────────────────  ────────────────────────────────────────────
    #   user/message       content: list[ContentBlock]          ●  领取用户输入
    #   turn/start         turn: int, trigger: {"kind": "message"}  开轮
    #   step/start         turn: int, step: int                 一步开张
    #   assistant/chunk    turn, step, chunk: StreamChunk       ●  六种 chunk 之一（回放/UI 数据，不进投影）
    #   assistant/message  turn, step, content: list[ContentBlock]  ●  组装完毕的完整回复
    #   assistant/usage    turn, step, usage: TokenUsage         ●  本 step 的 token 记账（M4-01）
    #   compaction/end     upto_seq: int, summary: str              压缩哨兵（M4-02）：seq ≤ upto_seq
    #                                                             的叙事已折叠为 summary，投影时重建
    #   tool/call          turn, step, call_id: str, name: str,
    #                      arguments: str                          模型产出的原始 JSON 串
    #   tool/result        turn, step, call_id: str,
    #                      content: list[ContentBlock],         ●
    #                      is_error: bool                          失败也是数据，不是异常
    #   steering/message   turn, content: list[ContentBlock]    ●  运行中插话
    #   context/message    content: list[ContentBlock]          ●  agent.inject 注入，不触发 turn
    #   step/end           turn, step                           一步收工
    #   error              turn, step, message: str             模型调用失败（step/end 之后）
    #   turn/end           turn, reason: str                    completed|error|aborted|max-steps
    #
    # 记忆钩子：凡 content / chunk 字段必装 dataclass 对象，其余字段全是
    # JSON 原生类型——序列化边界只需照顾前两类字段。
    def append(self, type: str, data: dict) -> SessionEvent:
        event = SessionEvent(
            type=type,
            seq=len(self._events),
            time=int(time.time() * 1000),
            data=data,
        )
        self._events.append(event)
        return event

    def next_turn_number(self) -> int:
        """下一个轮次号 = 日志里最后一个 turn/start 的编号 + 1（对照 loop.ts 的
        nextTurnNumber：从后往前扫，找最近一次开轮）。"""
        for event in reversed(self._events):
            if event.type == "turn/start":
                return event.data["turn"] + 1
        return 1

    # ── TODO(N)：usage 报表 —— M4-01 亲手写 ──────────────────────────
    # ①语义：账本是日志的又一个投影——扫 assistant/usage 事件做汇总，
    #        给 M4-02 的压缩触发提供数据。返回 dict（或小 dataclass，你定）。
    # ②伪代码：
    #   遍历 self._events：type == "assistant/usage" 的，
    #       累加 e.data["usage"].input_tokens / output_tokens
    #   return {"input_tokens": 总输入, "output_tokens": 总输出}
    # def usage_report(self) -> dict: ...
    def usage_report(self) -> dict:
        input_token = output_token = 0
        for event in self._events:
            if event.type == "assistant/usage":
                input_token += event.data["usage"].input_tokens
                output_token += event.data["usage"].output_tokens

        return {"input_tokens": input_token, "output_tokens": output_token}

    # ── TODO(P)：压缩 —— M4-02 亲手写 ────────────────────────────────
    # ①语义：append-only 的日志没有「删除」——压缩 = 追加一条 compaction/end
    #        哨兵事件：声明「seq ≤ upto_seq 的叙事已折叠为 summary」。
    #        摘要 v0 用截断拼接 stub（把被覆盖的 user/assistant/tool 内容
    #        拼成短文本），真摘要（LLM 自摘要）是进阶项。
    # ②伪代码：
    #   pieces = []
    #   遍历 seq ≤ upto_seq 的事件，user/message、assistant/message、
    #   tool/result 的文本片段收进 pieces（每条截到 ~50 字符）
    #   summary = "\n".join(pieces)
    #   return self.append("compaction/end", {"upto_seq": upto_seq, "summary": summary})
    # def compact(self, upto_seq: int) -> SessionEvent: ...

    def derive_messages(self) -> list[Message]:
        """把日志投影成模型历史（对照 Session.deriveMessages()）。

        关键洞察：LLM 词汇表里没有「tool」角色——工具结果作为 **user 角色**
        的消息、携带 tool-result 内容块回填（OpenAI/Anthropic 系工具回传的
        通用形态，各家的 wire format 差异由 adapter 吸收）。
        """
        messages: list[Message] = []
        # ── TODO(O)：投影哨兵规则 —— M4-02 亲手写 ────────────────────────
        # ①语义：derive_messages 遇到 compaction/end 时，把已累积的 messages
        #        整体替换为一条摘要消息（复用 <context> 信封思想：
        #        TextBlock(f"<compacted>{summary}</compacted>")）——此前的
        #        原文不再投影；之后的照旧累积。多次压缩以最后一次为准
        #        （后到的哨兵自然再次重建）。
        # ②伪代码（插在循环体最前）：
        #   if event.type == "compaction/end":
        #       messages = [Message(role="user",
        #           content=[TextBlock(f"<compacted>{event.data['summary']}</compacted>")])]
        # ③注意：这比「记住压缩点、分段遍历」简单一个量级，且天然支持多次压缩。
        for event in self._events:
            if event.type == "user/message":
                messages.append(Message(role="user", content=event.data["content"]))
            elif event.type == "assistant/message":
                messages.append(Message(role="assistant", content=event.data["content"]))
            elif event.type == "tool/result":
                messages.append(
                    Message(
                        role="user",
                        content=[
                            ToolResultBlock(
                                tool_call_id=event.data["call_id"],
                                content=event.data["content"],
                                is_error=event.data["is_error"],
                            )
                        ],
                    )
                )
            elif event.type == "context/message":
                messages.append(
                    Message(role="user", content=_render_tagged("context", event.data["content"]))
                )
            elif event.type == "steering/message":
                messages.append(
                    Message(role="user", content=_render_tagged("steering", event.data["content"]))
                )
        return messages
