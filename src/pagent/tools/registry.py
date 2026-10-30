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
from typing import Any

from pydantic import BaseModel, Field, ValidationError, create_model

from pagent.core.types import ContentBlock, TextBlock, ToolSchema


@dataclass(frozen=True)
class ToolOutcome:
    """一次工具执行的结局；无论成败都回填给模型。"""

    call_id: str
    content: list[ContentBlock]
    is_error: bool = False


@dataclass(frozen=True)
class ToolDef:
    """注册表里的一行记录——两种来源，构造后同一种形态：

    - @tool（代码派生）：model 从签名生成，parameters = model 的 JSON Schema；
    - register()（数据到达）：model=None，parameters 原样采用，零加工。

    model 身兼二职（仅代码派生工具有）：说明书的来源（model_json_schema()）、
    宿主侧的校验器（model_validate）。None = 契约以数据到达，校验归 server。
    """

    name: str
    description: str
    parameters: dict
    fn: Callable
    model: type[BaseModel] | None


# 唯一注册表：@tool 与 register() 都写入这里（构造形态不同，存储形态同一）。
REGISTRY: dict[str, ToolDef] = {}


# ── M3-01 亲手写区 ── 按 TODO(P) → (Q) → (R) 顺序 ────────────────────────

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


def model_from_fn(fn: Callable) -> type[BaseModel]:
    fields: dict[str, tuple] = {}
    for name, param in inspect.signature(fn).parameters.items():
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            raise TypeError(f"函数名: {fn.__name__}, 参数名: {name} 缺少注解")
        if param.default is inspect.Parameter.empty:
            fields[name] = (annotation, ...)  # 这里的 ... 只是为了表示必填，None本身也有含义，所以用 ...
        else:
            fields[name] = (annotation, Field(default=param.default))
    return create_model(fn.__name__, **fields)

# TODO(Q)：@tool 装饰器 —— 装饰即登记
# ①语义：包住带类型注解的函数，用 TODO(P) 生成说明书模型，组装
#        ToolDef 存进 REGISTRY；返回原函数本身（它仍能被直接调用/单测）。
# ②伪代码：
#   def tool(description):            # 带参装饰器 = 两层函数
#       def wrap(fn):
#           model = model_from_fn(fn)
#           REGISTRY[fn.__name__] = ToolDef(fn.__name__, description,
#                                           model.model_json_schema(),  # 说明书
#                                           fn, model)                  # 实现 + 校验器
#           return fn
#       return wrap
# ③样例：
#   @tool(description="抓取微博热搜榜")
#   def fetch_weibo_hot_search(limit: int = 10) -> list[dict]: ...


def tool(description: str):
    def wrap(fn: Callable):
        name = fn.__name__
        model = model_from_fn(fn)
        REGISTRY[name] = ToolDef(name, description, model.model_json_schema(), fn, model)
        return fn
    return wrap


class ToolService:
    """唯一注册表是模块级 REGISTRY：@tool（代码派生契约）与 register()
    （数据到达契约）都写入它——本类只是它的读取与执行门面。
    v0 简化：所有实例共享一张表（单 agent 场景）；多 agent 隔离留给未来。
    """

    def register(
        self, name: str, description: str, parameters: dict, fn: Callable
    ) -> None:
        """裸说明书入口：契约以数据到达（MCP 等外来工具的形状）。

        model=None = 宿主侧无代码可校验——校验是 server 的事
        （校验跟代码走）；parameters 原样采用，零加工。
        """
        REGISTRY[name] = ToolDef(
            name=name, description=description, parameters=parameters, fn=fn, model=None
        )

    # ── TODO(R)：单表门面 + 校验跟代码走 —— 升级 schemas()/execute()，签名不变 ──
    # ①语义：
    #   schemas()：遍历唯一注册表 REGISTRY，每个 ToolDef 转成 ToolSchema——
    #              parameters 已经是 JSON Schema（构造时定型），直接用。
    #   execute()：单次查表；命中且 model 非 None（代码派生契约）→ 先
    #              model_validate：ValidationError → 字段级 is_error 结果，
    #              校验通过用 model_dump() 的值调 fn；model 为 None（数据
    #              到达契约）→ 不校验，参数原样给 fn（校验跟代码走）。
    # ②样例：@tool 工具 arguments = {"limit": "abc"} →
    #   ToolOutcome(call_id, is_error=True,
    #               content=[TextBlock("参数校验失败：limit … integer …")])

    def schemas(self) -> list[ToolSchema]:
        """唯一注册表的全部说明书，随请求发给模型。"""
        return [
            ToolSchema(name=tool.name, description=tool.description, parameters=tool.parameters)
            for tool in REGISTRY.values()
        ]

    async def execute(self, call_id: str, name: str, params: dict) -> ToolOutcome:
        tool = REGISTRY.get(name)
        if tool is None:
            return ToolOutcome(call_id, [TextBlock(f"未知工具 {name}")], True)
        if tool.model is not None:
            try:
                params = tool.model.model_validate(params).model_dump()
            except ValidationError as e:
                return ToolOutcome(
                    call_id=call_id, content=[TextBlock(text=f"参数校验失败 {e}")], is_error=True
                )

        try:
            result = tool.fn(**params)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            return ToolOutcome(
                call_id=call_id, content=[TextBlock(text=f"工具执行出错 {e}")], is_error=True
            )
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return ToolOutcome(call_id=call_id, content=[TextBlock(text=text)])