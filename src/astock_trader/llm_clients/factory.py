"""LLM 客户端工厂函数。"""

from __future__ import annotations

from typing import Any

from astock_trader.llm_clients.openai_client import OpenAICompatibleClient

# 各提供商的默认 base_url 映射
_PROVIDER_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "ollama": "http://localhost:11434/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "mimo": "https://api.xiaomimimo.com/v1",
}


def create_llm_client(
    provider: str = "openai",
    model: str = "deepseek-chat",
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.7,
    **kwargs: Any,
) -> OpenAICompatibleClient:
    """创建 LLM 客户端。

    所有支持 OpenAI 兼容 API 的提供商统一使用 ``OpenAICompatibleClient``。

    Parameters
    ----------
    provider : str
        提供商名称。支持: ``"openai"``, ``"deepseek"``, ``"qwen"`` / ``"dashscope"``,
        ``"glm"`` / ``"zhipu"``, ``"ollama"``, ``"openrouter"``, ``"siliconflow"``,
        ``"together"``, ``"groq"`` 等。
    model : str
        模型名称，默认 ``"deepseek-chat"``。
    base_url : str | None
        自定义 API 地址。若为 ``None`` 则根据 ``provider`` 自动选择。
    api_key : str | None
        API Key；本地模型（如 Ollama）可留空。
    temperature : float
        采样温度，默认 0.7。
    **kwargs
        透传给 ``ChatOpenAI`` 的额外参数。

    Returns
    -------
    OpenAICompatibleClient
        配置好的 LLM 客户端实例。

    Examples
    --------
    >>> client = create_llm_client(provider="deepseek", model="deepseek-chat", api_key="sk-...")
    >>> llm = client.get_llm()

    >>> client = create_llm_client(provider="ollama", model="qwen2.5:7b")
    >>> llm = client.get_llm()
    """
    provider_lower = provider.lower()

    # 自动解析 base_url
    if base_url is None:
        base_url = _PROVIDER_BASE_URLS.get(provider_lower)

    return OpenAICompatibleClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        **kwargs,
    )
