"""工具服务：注册「名字 → 实现」，按名执行，错误也变成结果回给模型。

对照：deepseek-harness@53d1ef4a74 packages/tools/src/index.ts。

seam 三件套：接口（工具 = schema + 执行函数）、提供方（这里注册的实现）、
消费方（agent loop）。v0 简化：没有 tools/execute 瀑布事件——那是
沙箱/审批插件的扩展点，M3 建事件总线时再立。参数校验由工具自己做
（M3 换成 pydantic + 自动 JSON Schema）。
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass

from pagent.types import ContentBlock, TextBlock, ToolSchema


@dataclass(frozen=True)
class ToolOutcome:
    """一次工具执行的结局；无论成败都回填给模型。"""

    call_id: str
    content: list[ContentBlock]
    is_error: bool = False


class ToolService:
    def __init__(self) -> None:
        # name -> (description, parameters, fn)
        self._tools: dict[str, tuple[str, dict, Callable]] = {}

    def register(
        self, name: str, description: str, parameters: dict, fn: Callable
    ) -> None:
        """登记一个工具。fn 接收关键字参数，返回 str（或可 JSON 化的对象）。"""
        self._tools[name] = (description, parameters, fn)

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
