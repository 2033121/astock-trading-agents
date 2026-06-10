"""Signal extraction — parse the final decision text into a structured rating.

The :class:`SignalProcessor` wraps the ``parse_rating`` utility to provide
a clean interface for the orchestrator.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from astock_trader.agents.utils.rating import parse_rating

logger = logging.getLogger(__name__)


class SignalProcessor:
    """Extract a trading signal (rating) from the final decision text.

    Parameters
    ----------
    quick_thinking_llm : BaseChatModel | None
        Reserved for future use (e.g. LLM-based signal refinement).
        Currently unused; rating is extracted via regex-based parsing.
    """

    def __init__(self, quick_thinking_llm: Optional[Any] = None) -> None:
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
            / ``"减持"`` / ``"卖出"``.  Falls back to ``"持有"`` when
            parsing fails.
        """
        if not full_signal:
            logger.warning("Empty signal text; returning default rating.")
            return "持有"

        rating = parse_rating(full_signal)
        logger.info("Signal extracted: %s", rating)
        return rating
