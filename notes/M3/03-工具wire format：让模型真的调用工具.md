# M3 · 第 3 节 · 工具 wire format：让模型真的调用工具

> 备课出处（选读）：`deepseek-harness` 的 `ab19fed77c`（DeepSeek 适配器）、`packages/llm` 词汇类型；对照本仓库 [src/pagent/deepseek.py](../../src/pagent/deepseek.py) 现状与 [demos/common.py](../../demos/common.py) 里「工具 wire format 是 M3 主菜（M2-01 遗留）」的注记。

## 本节目标

补上全链路最后一块拼图：**adapter 的工具方言**——工具说明书发出去、`tool_calls` 流式收回来、工具结果按 wire 回填。完成后 DeepSeek 第一次真的调用 `bash_run`；收官亲手点：加一个你自己想要的工具。

## 1. 一句话理解

loop 和工具两侧早已就绪，缺的只是 adapter 的三段翻译——**说明书随请求走、`tool_calls` 随流式回、结果按 `tool_call_id` 对账回填**；wire format 只活在 adapter 里，出了这个文件谁都不用知道 DeepSeek 的方言。

## 2. 概念讲解：三侧就绪度盘点

| 侧 | 状态 | 凭据 |
|---|---|---|
| loop 侧 | ✅ M1 全就绪 | `schemas()` 进 `GenerateOptions.tools`、`tool_calls` → 执行 → `tool/result` 落日志、`derive_messages` 投影回填 |
| 工具侧 | ✅ M3-01/02 就绪 | `@tool` 自动说明书 + pydantic 校验 + `bash_run` 真工具 |
| adapter 侧 | ⚠️ **只做了一半** | `translate_event` 已会收 `tool_calls` 分片（M2-01 采过样）；但 `_build_body` **忽略 `options.tools`**，且 content 拼接只认 `TextBlock`——历史里的 `ToolResultBlock` 会被拼成空串（工具结果在上下文里蒸发！） |

adapter 要补的是三个方向：

**请求方向——说明书随行**。`ToolSchema` 直译成 DeepSeek/OpenAI 兼容形状，随请求发出：

```json
{"model": "…", "stream": true,
 "tools": [{"type": "function",
            "function": {"name": "bash_run",
                         "description": "在宿主机 shell 里执行一条命令…",
                         "parameters": {"type": "object", "properties": {"…": {}}}}]}
```

**响应方向——已就绪**。`tool_calls` 流式分片（参数拆多帧、id/name 只首帧出现）→ `ToolCallDelta` → assembler 组装 `ToolCallBlock`（M1-04 就绪）→ `finish_reason: "tool_calls"` → 方向盘判定「欠模型一次请求」→ 执行。这段 M2-01 已通，本节只回顾。

**回程方向——本节新知识点**。工具结果怎么回到模型面前？DeepSeek/OpenAI 用**角色制**：assistant 消息挂 `tool_calls` 数组（它调用过什么），工具结果用独立的 `role: "tool"` 消息逐条回填：

```json
{"role": "assistant", "content": "",
 "tool_calls": [{"id": "call-1", "type": "function",
                 "function": {"name": "bash_run", "arguments": "{\"command\": \"echo hi\"}"}}]},
{"role": "tool", "tool_call_id": "call-1", "content": "hi\n"}
```

注意两件事：① **`tool_call_id` 是对账凭据**——模型按 id 核对「我调的哪个调用、拿到了哪个结果」，必须原样回传；② 我们的中性词汇是 `derive_messages` 产出的 `Message`（assistant 带 `ToolCallBlock`、user 带 `ToolResultBlock`）——「工具结果作为 user 角色」是 M1-02 定的**中性设计**，各家 role 制方言由 adapter 吸收，这正是「词汇表对任何模型都成立」的又一次兑现。

```mermaid
%%{init: {"fontFamily": "Microsoft YaHei"}}%%
sequenceDiagram
    participant M as DeepSeek
    participant A as DeepSeekAdapter
    participant L as run_loop
    participant T as bash_run
    L->>A: GenerateOptions（含 tools 说明书）
    A->>M: POST /chat/completions<br/>tools: [{type:function,…}]
    M-->>A: SSE：tool_calls 分片 → finish=tool_calls
    A-->>L: ToolCallDelta* → ToolCallBlock → Finish
    L->>L: tool/call 落日志 → 校验 → 执行
    L->>T: execute(call_id, name, args)
    T-->>L: ToolOutcome（正文整形 / is_error）
    L->>L: tool/result 落日志 → 投影回填
    L->>A: 下一轮请求（历史含 ToolResultBlock）
    A->>M: messages 里 role:"tool" + tool_call_id
    M-->>A: 模型读到命令结果，继续对话
```

读图要点：adapter 出现两次（请求方向译说明书、回程方向译角色制）——**wire format 的进出都在这一个文件闭合**；loop 对 DeepSeek 的存在零感知。

## 3. 关键代码片段讲解

现状的两处缺口（[src/pagent/deepseek.py](../../src/pagent/deepseek.py)，你 M2-01 的代码）：

```python
def _build_body(self, options: GenerateOptions) -> dict:
    ...
    for m in options.messages:
        content = "".join([tb.text for tb in m.content if isinstance(tb, TextBlock)])
        #          ↑ 只认 TextBlock：ToolResultBlock 被静默丢弃 → content 变空串
        messages.append({"role": m.role, "content": content})
    return {"model": options.model, "messages": messages, "stream": True}
    #     ↑ options.tools 没有出场——模型根本不知道有工具存在
```

读法：这不是 bug，是 M2-01 当时的**范围纪律**（工具 wire format 留给 M3）——现在范围到了。本节编码就是把这两处补全：`_build_body` 增加工具说明书序列化 + 消息翻译升级（assistant 的 `ToolCallBlock` → `tool_calls` 数组；user 的 `ToolResultBlock` → `role:"tool"` 消息）。

## 4. 备课出处（选读）

- `git -C deepseek-harness show ab19fed77c`（DeepSeek 适配器：请求构造与流式翻译的分层，与我们的 TODO(A)~(D) 同构）
- 本仓库 `src/pagent/deepseek.py` 的 `SSE_SAMPLE`（tool_calls 分片的真实 wire 采样，M2-01 教训：每帧都带 `finish_reason` 键、中间帧为 null）
- [demos/common.py](../../demos/common.py) `build_agent` 注释：「工具结果的 wire format 是 M3 主菜（M2-01 遗留）」

## 5. 编码任务

【待补充——M3-02 完成收尾时与脚手架一同补全（`_build_body` 的 tools 序列化 + 角色制消息翻译 + fetch_weibo 真工具 + demo 接线）】

## 6. 运行与验证

【待补充——同上】

## 7. TS vs Python 差异与坑

- 无新语言差异——本节是新知识在两边对称：harness 的 llm-deepseek 同样要在 adapter 内消化 role 制方言。
- 坑预告：`content` 对 assistant 带 `tool_calls` 的消息应为空串或省略；`role:"tool"` 消息**必须**带 `tool_call_id`，漏了 DeepSeek 直接 400。

## 8. 待探索清单

- 并行工具调用（一条消息多个 tool_calls 的执行顺序与并发）
- function calling 的 strict / json_schema 模式
- MCP 桥：把 MCP server 的工具接进 REGISTRY（M3-01 疑点 Q5 的实装）

## 9. 小结与遗留问题

- 工具全链路 = 说明书随行 + tool_calls 流式回收 + role 制回填，三段都关在 adapter 里。
- `tool_call_id` 是模型的对账凭据，原样回传。
- 遗留：M4 上下文管理（工具结果很长时上下文膨胀——`bash_run` 输出截断的另一半理由）。
