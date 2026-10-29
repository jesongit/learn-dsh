"""工具服务：注册「名字 → 实现」，按名执行，错误也变成结果回给模型。

对照：deepseek-harness@53d1ef4a74 packages/tools/src/index.ts；
M3-01 起另对照 8b5a3ef730（bash 工具三件套）与 ef45ca823a（defineTool DSL）。

seam 三件套：接口（工具 = schema + 执行函数）、提供方（这里注册的实现）、
消费方（agent loop）。v0 简化：没有 tools/execute 瀑布事件——那是
沙箱/审批插件的扩展点，M3 建事件总线时再立。
M3-01 升级：说明书（JSON Schema）从类型注解自动生成（手写 parameters 的
「两份真相」病根治），执行前 pydantic 校验——校验失败仍是「错误当数据」，
但错误质量升到字段级。
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from pagent.types import ContentBlock, TextBlock, ToolSchema


@dataclass(frozen=True)
class ToolOutcome:
    """一次工具执行的结局；无论成败都回填给模型。"""

    call_id: str
    content: list[ContentBlock]
    is_error: bool = False


@dataclass(frozen=True)
class ToolDef:
    """@tool 登记后的一行记录：说明书（pydantic 模型）+ 实现函数。

    model 从函数签名自动生成（TODO(P)）——它身兼二职：
    给模型看的 JSON Schema 的来源（model_json_schema()）、
    执行前的参数校验器（model_validate）。
    """

    name: str
    description: str
    model: type[BaseModel]
    fn: Callable


# 模块级注册表：@tool 装饰即登记（TODO(Q)）；ToolService.schemas() 来这里聚合。
REGISTRY: dict[str, ToolDef] = {}


class ToolService:
    def __init__(self) -> None:
        # name -> (description, parameters, fn)  ← M1 手写说明书的老路，保留作回归护栏
        self._tools: dict[str, tuple[str, dict, Callable]] = {}

    def register(
        self, name: str, description: str, parameters: dict, fn: Callable
    ) -> None:
        """登记一个工具。fn 接收关键字参数，返回 str（或可 JSON 化的对象）。"""
        self._tools[name] = (description, parameters, fn)

    # ── M3-01 亲手写区 ── 按 TODO(P) → (Q) → (R) 顺序 ────────────────────

    # TODO(P)：签名 → pydantic 模型 —— 说明书自动生成的核心
    # ①语义：函数的每个参数变成模型的一个字段——类型注解即字段类型，
    #        默认值即 Field default；带默认 = 可选，不带默认 = 必填。
    #        模型名用函数名。（v0 纪律：工具函数一律带类型注解。）
    # ②伪代码：
    #   遍历 inspect.signature(fn).parameters：
    #       参数带默认值 → 字段 = (注解, Field(default=默认值))
    #       参数无默认值 → 字段 = (注解, ...)          # pydantic 的必填写法
    #   return create_model(fn.__name__, **字段表)
    # ③样例：def f(limit: int = 10) →
    #   create_model("f", limit=(int, Field(default=10)))
    #   该模型 .model_json_schema() 的 properties["limit"]
    #   == {"type": "integer", "default": 10}
    # def model_from_fn(fn: Callable) -> type[BaseModel]: ...

    # TODO(Q)：@tool 装饰器 —— 装饰即登记
    # ①语义：包住带类型注解的函数，用 TODO(P) 生成说明书模型，组装
    #        ToolDef 存进 REGISTRY；返回原函数本身（它仍能被直接调用/单测）。
    # ②伪代码：
    #   def tool(description):            # 带参装饰器 = 两层函数
    #       def wrap(fn):
    #           REGISTRY[fn.__name__] = ToolDef(fn.__name__, description,
    #                                           model_from_fn(fn), fn)
    #           return fn
    #       return wrap
    # ③样例：
    #   @tool(description="抓取微博热搜榜")
    #   def fetch_weibo_hot_search(limit: int = 10) -> list[dict]: ...
    # def tool(description: str): ...

    # TODO(R)：注册表聚合 + 校验先行 —— 升级 schemas()/execute()，签名不变
    # ①语义：
    #   schemas()：在 M1 列表之外，把 REGISTRY 里每个 ToolDef 也转成
    #              ToolSchema——parameters 用 model.model_json_schema()。
    #   execute()：名字命中 REGISTRY 时先 model_validate(arguments)；
    #              ValidationError → is_error 的 ToolOutcome，消息精确到
    #              字段（「limit 应为 integer，收到 str」级别，模型一次改对）；
    #              校验通过 → 用校验后的值调 fn（后续处理与 M1 相同）。
    #              M1 老路（self._tools）行为一字不改。
    # ②样例：arguments = {"limit": "abc"} →
    #   ToolOutcome(call_id, is_error=True,
    #               content=[TextBlock("参数校验失败：limit … integer …")])

    def schemas(self) -> list[ToolSchema]:
        """已注册工具的说明书，随请求发给模型。"""
        return [
            ToolSchema(name=name, description=description, parameters=parameters)
            for name, (description, parameters, _fn) in self._tools.items()
        ]

    async def execute(self, call_id: str, name: str, arguments: dict) -> ToolOutcome:
        entry = self._tools.get(name)
        if entry is None:
            return ToolOutcome(
                call_id=call_id,
                content=[TextBlock(text=f"未知工具：{name}")],
                is_error=True,
            )
        _description, _parameters, fn = entry
        try:
            result = fn(**arguments)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:  # 工具炸了不炸 loop：错误也回给模型，让它自行调整
            return ToolOutcome(
                call_id=call_id,
                content=[TextBlock(text=f"工具执行出错：{e}")],
                is_error=True,
            )
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return ToolOutcome(call_id=call_id, content=[TextBlock(text=text)])
