"""Initial state creation and graph invocation helpers.

The :class:`Propagator` is responsible for:
  * Building the zero-value ``AgentState`` dictionary.
  * Providing graph invocation arguments (e.g. recursion limit).
"""

from __future__ import annotations

from typing import Any


class Propagator:
    """Factory for initial graph state and invocation parameters.

    Parameters
    ----------
    max_recur_limit : int
        Maximum recursion depth for the LangGraph execution.
        Defaults to 100.
    """

    def __init__(self, max_recur_limit: int = 100) -> None:
        self.max_recur_limit = max_recur_limit

    # ────────────────────────────────────────────────────────────
    #  Initial state
    # ────────────────────────────────────────────────────────────

    @staticmethod
    def create_initial_state(
        company_name: str,
        trade_date: str,
        past_context: str = "",
    ) -> dict[str, Any]:
        """Build a zero-value initial state for the trading graph.

        Parameters
        ----------
        company_name : str
            Stock ticker or company name, e.g. ``"000001"`` or ``"平安银行"``.
        trade_date : str
            Trade date in ``YYYY-MM-DD`` format.
        past_context : str
            Historical decision context loaded from memory log.

        Returns
        -------
        dict
            A dictionary conforming to :class:`AgentState` with all fields
            initialised to their empty / zero values.
        """
        return {
            # -- Messages (MessagesState reducer handles accumulation) --
            "messages": [],
            # -- Core context --
            "company_of_interest": company_name,
            "trade_date": trade_date,
            "sender": "",
            # -- Analyst reports --
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            # -- Investment debate --
            "investment_debate_state": {
                "bull_history": [],
                "bear_history": [],
                "history": [],
                "current_response": "",
                "judge_decision": "",
                "count": 0,
            },
            "investment_plan": "",
            "trader_investment_plan": "",
            # -- Risk debate --
            "risk_debate_state": {
                "aggressive_history": [],
                "conservative_history": [],
                "neutral_history": [],
                "history": [],
                "latest_speaker": "",
                "current_aggressive_response": "",
                "current_conservative_response": "",
                "current_neutral_response": "",
                "judge_decision": "",
                "count": 0,
            },
            # -- Final output --
            "final_trade_decision": "",
            # -- Report --
            "report_path": "",
            # -- Memory --
            "past_context": past_context,
        }

    # ────────────────────────────────────────────────────────────
    #  Graph invocation args
    # ────────────────────────────────────────────────────────────

    def get_graph_args(self) -> dict[str, Any]:
        """Return keyword arguments for ``compiled_graph.invoke()``.

        Returns
        -------
        dict
            ``{"recursion_limit": <limit>}``
        """
        return {"recursion_limit": self.max_recur_limit}
