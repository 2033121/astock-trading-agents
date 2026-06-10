"""LLM 客户端抽象基类。"""

from abc import ABC, abstractmethod


class BaseLLMClient(ABC):
    """所有 LLM 客户端的抽象基类。

    子类必须实现 ``get_llm()`` 方法，返回一个可被 LangChain / LangGraph
    使用的 LLM 实例（如 ``ChatOpenAI``）。
    """

    @abstractmethod
    def get_llm(self):
        """返回底层 LLM 实例。"""
        pass

    def validate_model(self) -> bool:
        """验证模型配置是否有效。

        默认返回 ``True``；子类可覆盖以执行额外校验（如检查 API Key 是否可用、
        模型名称是否合法等）。
        """
        return True
