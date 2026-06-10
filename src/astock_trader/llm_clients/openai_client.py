"""OpenAI 兼容协议的 LLM 客户端。

所有支持 OpenAI 兼容 API 的提供商（OpenAI、DeepSeek、通义千问 DashScope、
智谱 GLM、Ollama、OpenRouter 等）都使用此客户端。
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from astock_trader.llm_clients.base_client import BaseLLMClient


class OpenAICompatibleClient(BaseLLMClient):
    """基于 ``langchain_openai.ChatOpenAI`` 的通用 OpenAI 兼容客户端。

    Parameters
    ----------
    model : str
        模型名称，如 ``"deepseek-chat"``、``"qwen-plus"``、``"gpt-4o"``。
    base_url : str | None
        API 根地址。若为 ``None`` 则使用 OpenAI 官方地址。
    api_key : str | None
        API Key；若未提供则使用 ``"not-needed"`` 占位（适用于本地模型）。
    temperature : float
        采样温度，默认 0.7。
    **kwargs
        透传给 ``ChatOpenAI`` 的额外参数（如 ``max_tokens``、``top_p`` 等）。
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key or "not-needed"
        self.temperature = temperature
        self._extra_kwargs = kwargs

        self.client = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=self.api_key,
            temperature=temperature,
            **kwargs,
        )

    def get_llm(self) -> ChatOpenAI:
        """返回底层 ``ChatOpenAI`` 实例。"""
        return self.client

    def validate_model(self) -> bool:
        """检查模型名称和 API Key 是否已配置。"""
        if not self.model:
            return False
        if self.api_key == "not-needed" and self.base_url and "localhost" not in self.base_url:
            # 远程服务通常需要有效 API Key
            return False
        return True

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleClient(model={self.model!r}, base_url={self.base_url!r}, temperature={self.temperature})"
        )
