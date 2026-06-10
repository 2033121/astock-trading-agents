"""Flow control — conditional routing logic for the LangGraph pipeline.

Each ``should_continue_*`` method inspects the current ``AgentState`` and
returns a string label that LangGraph uses to select the next node.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ConditionalLogic:
    """Encapsulates all conditional edge routing for the trading graph.

    Parameters
    ----------
    max_debate_rounds : int
        Maximum number of full bull/bear debate rounds before the Research
        Manager intervenes.  Each round produces one bull + one bear message,
        so the debate counter threshold is ``2 * max_debate_rounds``.
    max_risk_discuss_rounds : int
        Maximum number of full risk-discussion rounds (aggressive -> conservative
        -> neutral) before the Portfolio Manager takes over.  Threshold is
        ``3 * max_risk_discuss_rounds``.
    """

    def __init__(
        self,
        max_debate_rounds: int = 1,
        max_risk_discuss_rounds: int = 1,
    ) -> None:
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    # ────────────────────────────────────────────────────────────
    #  Analyst tool-loop routing
    # ────────────────────────────────────────────────────────────

    @staticmethod
    def _has_tool_calls(state: Dict[str, Any]) -> bool:
        """Return True when the last AI message contains tool_calls."""
        messages = state.get("messages", [])
        if not messages:
            return False
        last = messages[-1]
        return hasattr(last, "tool_calls") and bool(last.tool_calls)

    def should_continue_market(self, state: Dict[str, Any]) -> str:
        """Route after Market Analyst: tool loop or advance."""
        if self._has_tool_calls(state):
            return "tools_market"
        return "Msg Clear Market"

    def should_continue_social(self, state: Dict[str, Any]) -> str:
        """Route after Social/Sentiment Analyst: tool loop or advance."""
        if self._has_tool_calls(state):
            return "tools_social"
        return "Msg Clear Social"

    def should_continue_news(self, state: Dict[str, Any]) -> str:
        """Route after News Analyst: tool loop or advance."""
        if self._has_tool_calls(state):
            return "tools_news"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state: Dict[str, Any]) -> str:
        """Route after Fundamentals Analyst: tool loop or advance."""
        if self._has_tool_calls(state):
            return "tools_fundamentals"
        return "Msg Clear Fundamentals"

    # ────────────────────────────────────────────────────────────
    #  Investment debate (Bull vs Bear)
    # ────────────────────────────────────────────────────────────

    def should_continue_debate(self, state: Dict[str, Any]) -> str:
        """Route after a debate turn.

        Returns
        -------
        str
            ``"Research Manager"`` when debate is exhausted,
            ``"Bear Researcher"`` when the latest message is bullish,
            ``"Bull Researcher"`` otherwise (default / bearish message).
        """
        debate_state = state.get("investment_debate_state", {})
        count = debate_state.get("count", 0)
        current_response = debate_state.get("current_response", "")

        if count >= 2 * self.max_debate_rounds:
            return "Research Manager"

        if current_response.startswith("看多"):
            return "Bear Researcher"

        return "Bull Researcher"

    # ────────────────────────────────────────────────────────────
    #  Risk debate (Aggressive / Conservative / Neutral)
    # ────────────────────────────────────────────────────────────

    def should_continue_risk_analysis(self, state: Dict[str, Any]) -> str:
        """Route after a risk-analyst turn.

        The three analysts rotate in a fixed cycle:
        ``Aggressive -> Conservative -> Neutral -> Aggressive -> ...``

        Returns
        -------
        str
            ``"Portfolio Manager"`` when the round limit is reached,
            otherwise the name of the next analyst in the cycle.
        """
        risk_state = state.get("risk_debate_state", {})
        count = risk_state.get("count", 0)
        latest_speaker = risk_state.get("latest_speaker", "")

        if count >= 3 * self.max_risk_discuss_rounds:
            return "Portfolio Manager"

        if latest_speaker.startswith("激进"):
            return "Conservative Analyst"
        if latest_speaker.startswith("保守"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
