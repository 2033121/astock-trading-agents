"""Post-decision reflection — LLM-generated retrospective on trading decisions.

After the graph produces a final trade decision and the actual market outcome
becomes available, the :class:`Reflector` generates a concise reflection that
is stored in the memory log for future context.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是一个交易分析师，回顾过去的决策。写2-4句话：\n"
    "1. 方向是否正确？\n"
    "2. 论点哪部分成立、哪部分失败？\n"
    "3. 一条具体教训。\n\n"
    "保持简洁、具体、可操作。"
)


class Reflector:
    """Generate LLM-based reflections on past trading decisions.

    Parameters
    ----------
    quick_thinking_llm : BaseChatModel | None
        A LangChain chat model used for fast reflection generation.
        If ``None``, reflection is skipped and a placeholder is returned.
    """

    def __init__(self, quick_thinking_llm: Any | None = None) -> None:
        self.quick_thinking_llm = quick_thinking_llm

    def reflect_on_final_decision(
        self,
        final_decision: str,
        raw_return: float,
        alpha_return: float,
    ) -> str:
        """Generate a 2-4 sentence reflection on a past decision.

        Parameters
        ----------
        final_decision : str
            The original final trade decision text (Markdown).
        raw_return : float
            Actual raw return of the position (e.g. 0.05 for +5 %).
        alpha_return : float
            Actual alpha (excess) return vs. benchmark.

        Returns
        -------
        str
            A concise reflection string, or a placeholder if no LLM is
            available.
        """
        if self.quick_thinking_llm is None:
            logger.debug("No quick-thinking LLM configured; skipping reflection.")
            return "[未配置 LLM，跳过反思]"

        human_msg = f"收益率: {raw_return:+.1%}\n超额收益: {alpha_return:+.1%}\n\n决策:\n{final_decision}"
        messages = [
            ("system", _SYSTEM_PROMPT),
            ("human", human_msg),
        ]

        try:
            response = self.quick_thinking_llm.invoke(messages)
            reflection_text = response.content
            logger.debug("Reflection generated (%d chars)", len(reflection_text))
            return reflection_text
        except Exception as exc:
            logger.warning("Reflection generation failed: %s", exc)
            return f"[反思生成失败: {exc}]"
