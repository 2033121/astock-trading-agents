"""Structured output binding — 结构化输出绑定与降级调用。

优先使用 LLM 的 ``with_structured_output`` 能力（如 OpenAI function calling），
若模型不支持则降级为自由文本输出。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def bind_structured(llm: Any, schema: type, agent_name: str) -> Any | None:
    """尝试为 LLM 绑定结构化输出 schema。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。
    schema : type
        Pydantic BaseModel 子类。
    agent_name : str
        调用方 Agent 名称，仅用于日志。

    Returns
    -------
    Optional[Any]
        绑定后的结构化 LLM；若不支持则返回 ``None``。
    """
    try:
        structured_llm = llm.with_structured_output(schema)
        logger.debug("[%s] 结构化输出绑定成功: %s", agent_name, schema.__name__)
        return structured_llm
    except Exception as exc:
        logger.debug("[%s] 结构化输出绑定失败 (%s): %s", agent_name, schema.__name__, exc)
        return None


def invoke_structured_or_freetext(
    structured_llm: Any | None,
    plain_llm: Any,
    prompt: str | list[tuple[str, str]],
    render: Callable[[Any], str],
    agent_name: str,
) -> str:
    """优先调用结构化 LLM，失败后降级为自由文本。

    Parameters
    ----------
    structured_llm : Optional[Any]
        由 ``bind_structured`` 返回的结构化 LLM，或 ``None``。
    plain_llm : BaseChatModel
        原始 LangChain 聊天模型，用于降级调用。
    prompt : str | list[tuple[str, str]]
        提示词。可以是纯字符串或 LangChain 消息列表。
    render : Callable
        将结构化输出模型实例转换为 Markdown 字符串的函数。
    agent_name : str
        调用方 Agent 名称，仅用于日志。

    Returns
    -------
    str
        渲染后的 Markdown 文本或 LLM 自由文本回复。
    """
    # ── 结构化调用 ──────────────────────────────────────────
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            rendered = render(result)
            logger.debug("[%s] 结构化输出成功", agent_name)
            return rendered
        except Exception as exc:
            logger.warning("[%s] 结构化输出调用失败，降级为自由文本: %s", agent_name, exc)

    # ── 自由文本降级 ────────────────────────────────────────
    if isinstance(prompt, list):
        result = plain_llm.invoke(prompt)
    else:
        result = plain_llm.invoke([("human", prompt)])

    logger.debug("[%s] 自由文本降级完成", agent_name)
    return result.content
