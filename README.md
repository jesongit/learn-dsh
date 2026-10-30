# PAgent · learn-dsh

**用 Python 从零手写一个 Agent，对照精读 DeepSeek Harness 的源码演进——整个仓库就是一部边学边写的教材。**

[DeepSeek Harness](deepseek-harness/) 是 DeepSeek 官方开源的 TypeScript Agent 框架。本仓库沿它的 git 历史主线切片学习，用 Python 把 Agent 的核心逐节复刻出来：**15 个学习节、53 个测试、17 篇图文教材**，从「什么是 agent loop」一路写到「重启进程，会话恢复」。

## Agent = 模型 + 循环 + 工具 + 上下文管理

等式的每一项都是亲手实现的：

| 能力 | 位置 | 说明 |
|---|---|---|
| 事件日志 | `src/pagent/core/session.py` | 只追加的单一事实来源，12 种事件词汇表；模型历史与 UI 都是它的投影 |
| agent loop | `src/pagent/core/loop.py` | turn / step / 双收件箱 / steering / abort / 永续挂起 |
| 词汇表 | `src/pagent/core/types.py` | Message · StreamChunk · ToolSchema——对任何模型都成立的中性语言 |
| 适配器 seam | `src/pagent/llm/` | 接口 + Mock + DeepSeek（HTTP/SSE 流式翻译），换模型零改上层 |
| 工具系统 | `src/pagent/tools/` | 注册表 + `@tool` 自动生成 JSON Schema（pydantic）+ 校验失败回模型的错误分层管线 |
| 真工具 | `src/pagent/tools/` | bash 执行（结果整形 + 错误分层）、微博热搜、委派子代理 |
| 上下文管理 | `core/session.py` + `core/loop.py` | token 记账事件 + 压缩哨兵 + 投影重建，历史不再无限增长 |
| 委派 | `src/pagent/tools/tool_subagent.py` | 把子任务交给独立子 agent，父级只回收终态 |
| 持久化 | `src/pagent/persistence.py` | JSONL 双向边界：保存打类型标签，恢复按词汇表重建，重启即续聊 |
| 两种入口 | `demos/` | 终端对话（会话自动存档恢复）与 Web UI（SSE 打字机 / 插话 / 中断） |

## 快速开始

```bash
# 1. 安装依赖（Python ≥ 3.13，uv 管理）
uv sync

# 2. 配置密钥
cp .env.example .env        # 填入 DEEPSEEK_API_KEY

# 3. 跑测试
uv run pytest               # 53 passed

# 4. 终端对话
uv run python -m demos.echo
#    quit 退出 · /stop 中断 · /steer <指示> 中途插话
#    会话自动存档到 echo_session.jsonl，重启进程自动恢复

# 5. Web UI（浏览器打开 http://127.0.0.1:8000）
uv run python -m demos.web
```

## 这个仓库怎么读：教材在 `notes/`

学习产出不只是代码——`notes/` 下有 17 篇图文教材，按里程碑分章，每节固定模板：**目标 → 概念讲解 → 关键代码片段 → 编码实录（bug 谱系）→ 运行验证 → TS vs Python 差异 → 对话疑点**。

| 章 | 内容 |
|---|---|
| [00 总览与设计](notes/00-总览与设计.md) | harness 全景、Agent 等式、types 词汇地图 |
| [M1 最小循环](notes/M1/01-接缝先行.md) | 词汇表 → mock 回放 → 工具往返 → 错误路径，echo 说出第一句话 |
| [M2 真实 LLM 与流式](notes/M2/01-真实适配器.md) | DeepSeek 适配器、中断与挂起、终端真聊、Web UI |
| [M3 工具系统](notes/M3/01-工具说明书自动生成.md) | `@tool` 自动说明书、bash 错误分层、工具 wire format |
| [M4 上下文管理](notes/M4/01-上下文是硬预算token记账.md) | token 记账、压缩哨兵与投影重建 |
| [M5 子代理](notes/M5/01-委派：把子任务交给另一个自己.md) | 委派 seam、工厂模式三梯度、上下文经济学 |
| [M6 会话持久化](notes/M6/01-会话持久化：日志离开进程.md) | JSONL 双向边界、重启恢复对话 |
| [术语表](notes/术语表.md) | 中英对照持续维护 |

每章的「编码实录」记录了真实的 bug 谱系与修复过程，「对话疑点」收录学习过程中追问出的设计规律——**踩过的坑本身就是教材的一部分**。

## 沿 git 历史重修

每个学习节都有「交付」（脚手架+教材）与「完成」（验收全绿）两个 tag 锚点，可以回到任意节点重做：

```bash
git tag -l "m*"             # 28 个锚点
git checkout m1-02-交付     # 回到「工具往返」的起点
git diff m1-02-交付 m1-02-完成   # 对照脚手架与实现
```

## 与 DeepSeek Harness 的关系

- 学习蓝图是其官方开源仓库（MIT），本地以只读副本随仓库目录放置、不入 git；
- **概念复刻，不是工程复刻**：复刻 loop、工具协议、上下文管理、子代理、持久化等 Agent 原理；不复刻 Cordis DI 容器、monorepo、覆盖率门禁等 TS 工程基建；
- PAgent 的对应物刻意朴素：Cordis 的「注册 + 扩展点」在 PAgent 里是**注册表模式 + 集中装配**（见 [PROGRESS.md](PROGRESS.md) 决策记录）。

## PAgent 2.0 规划

1.0 已按路线图收官（见 [PROGRESS.md](PROGRESS.md)）。2.0 的演进方向：

1. **REGISTRY 对象化**——注册表从模块级单表变为可多实例对象，支持子级工具隔离；
2. **事件总线**——Session 订阅推送取代轮询，审批 / 沙箱 / 实时 UI 的钩子地基；
3. **持久化层 pydantic 判别联合化**——恢复方向自动化（现状是手写重建器，见 [M6-01 教材](notes/M6/01-会话持久化：日志离开进程.md) 疑点 Q15）。

## 状态

- 测试：53 passed（`uv run pytest`）
- Python ≥ 3.13 · 依赖：httpx / fastapi / uvicorn / pydantic
- 运行产物 `*.jsonl` 与 `.env` 均不入库
