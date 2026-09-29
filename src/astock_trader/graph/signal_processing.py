"""Signal extraction — parse the final decision text into a structured rating.

The :class:`SignalProcessor` wraps the :func:`extract_rating` utility to provide
a clean interface for the orchestrator.

**解析不出来就报「待复核」，不假装成「持有」。** 把无法解析的决策静默降级成
中性评级，会让下游（记忆、报告、事后复盘）把它当成一个真实的持有判断；调用方
看到 :data:`~astock_trader.agents.utils.rating.RATING_REVIEW` 才知道该重跑或
人工介入（上游 TradingAgents #1170 同类修复）。
"""

from __future__ import annotations

import logging
from typing import Any

from astock_trader.agents.utils.rating import RATING_REVIEW, extract_rating

logger = logging.getLogger(__name__)


class SignalProcessor:
    """Extract a trading signal (rating) from the final decision text.

    Parameters
    ----------
    quick_thinking_llm : BaseChatModel | None
        Reserved for future use (e.g. LLM-based signal refinement).
        Currently unused; rating is extracted via regex-based parsing.
    """

    def __init__(self, quick_thinking_llm: Any | None = None) -> None:
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str) -> str:
        """Parse the full decision text and return the extracted rating.

        Parameters
        ----------
        full_signal : str
            The ``final_trade_decision`` text produced by the Portfolio
            Manager node.

        Returns
        -------
        str
            A Chinese rating string: ``"买入"`` / ``"增持"`` / ``"持有"``
            / ``"减持"`` / ``"卖出"``.  When no rating can be parsed, returns
            ``"待复核"`` (``RATING_REVIEW``) — an explicit "needs review"
            signal instead of a fabricated ``"持有"``.
        """
        if not full_signal:
            logger.warning("Empty signal text; returning REVIEW rating.")
            return RATING_REVIEW

        rating = extract_rating(full_signal)
        if rating is None:
            logger.warning(
                "No rating found in the final decision; returning REVIEW. Decision text starts with: %r",
                full_signal[:120],
            )
            return RATING_REVIEW

        logger.info("Signal extracted: %s", rating)
        return rating
