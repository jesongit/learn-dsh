"""LLM 适配器接缝（seam）—— PAgent 与具体模型之间的唯一边界。

对照：deepseek-harness@53d1ef4a74 packages/llm 的 LlmAdapter 抽象类
与 ctx.llm 服务。

seam 的三件套在这里齐了：
- 接口定义：LLMAdapter
- 提供方：任何子类（M1 的 MockAdapter、M2 的 DeepSeekAdapter）
- 消费方：agent loop（M1-02）只跟 LlmService.stream() 说话

于是「换模型」= 换注册进来的 adapter，loop 一行不改。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pagent.core.types import GenerateOptions, StreamChunk


class LLMAdapter(ABC):
    """所有模型适配器的接口：给一次请求，吐一段 chunk 流。

    实现必须是 async generator：

        class MyAdapter(LLMAdapter):
            async def stream(self, options):
                yield BlockStart(...)
                yield ...
    """

    @abstractmethod
    def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        # 抽象函数，要求对应 Adapter 必须实现 stream 方法
        raise NotImplementedError


class LlmService:
    """极简版 ctx.llm：按模型名把请求分发给注册的 adapter。

    同名模型后注册者覆盖先注册者——这也是一种 patch。 
    """

    def __init__(self) -> None:
        self._adapters: dict[str, LLMAdapter] = {}

    def register(self, models: list[str], adapter: LLMAdapter) -> None:
        for model in models:
            self._adapters[model] = adapter

    def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        try:
            adapter = self._adapters[options.model]
        except KeyError:
            raise LookupError(
                f"没有注册模型 {options.model!r}；已注册：{sorted(self._adapters)}"
            ) from None
        return adapter.stream(options)
