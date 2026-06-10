"""Main orchestrator — ``TradingAgentsGraph`` wires everything together.

This module is the single entry point that the CLI (and any external
caller) uses to run the multi-agent trading-decision pipeline.

Typical usage::

    from astock_trader.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(
        selected_analysts=["market", "news", "fundamentals"],
        config={...},
    )
    final_state, rating = graph.propagate("000001", "2025-06-10")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from astock_trader.agents.utils.memory import TradingMemoryLog
from astock_trader.default_config import DEFAULT_CONFIG
from astock_trader.graph.checkpointer import (
    clear_checkpoint,
    get_checkpointer,
    has_checkpoint,
    thread_id,
)
from astock_trader.graph.conditional_logic import ConditionalLogic
from astock_trader.graph.propagation import Propagator
from astock_trader.graph.reflection import Reflector
from astock_trader.graph.setup import GraphSetup
from astock_trader.graph.signal_processing import SignalProcessor

logger = logging.getLogger(__name__)


class TradingAgentsGraph:
    """High-level orchestrator for the multi-agent trading pipeline.

    Parameters
    ----------
    selected_analysts : list[str]
        Which analyst modules to include.  Valid values:
        ``"market"``, ``"social"``, ``"news"``, ``"fundamentals"``.
    debug : bool
        When ``True``, enables verbose LangGraph logging.
    config : dict | None
        Configuration dictionary.  Falls back to ``DEFAULT_CONFIG``.
    callbacks : list[Callable] | None
        Optional list of callback functions invoked at key stages.
        Each callback receives ``(event_name: str, data: dict)``.
    """

    def __init__(
        self,
        selected_analysts: Optional[List[str]] = None,
        debug: bool = False,
        config: Optional[Dict[str, Any]] = None,
        callbacks: Optional[List[Callable]] = None,
    ) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.selected_analysts = selected_analysts or [
            "market", "social", "news", "fundamentals"
        ]
        self.debug = debug
        self.callbacks = callbacks or []

        # ── Create LLM clients ────────────────────────────────
        self.deep_thinking_llm, self.quick_thinking_llm = self._create_llms()

        # ── Sub-components ────────────────────────────────────
        self.logic = ConditionalLogic(
            max_debate_rounds=self.config.get("max_debate_rounds", 1),
            max_risk_discuss_rounds=self.config.get("max_risk_discuss_rounds", 1),
        )
        self.graph_setup = GraphSetup(
            deep_thinking_llm=self.deep_thinking_llm,
            quick_thinking_llm=self.quick_thinking_llm,
            conditional_logic=self.logic,
            language=self.config.get("output_language", "Chinese"),
            report_output_dir=self.config.get("report_output_dir", ""),
        )
        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )
        self.reflector = Reflector(quick_thinking_llm=self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(
            quick_thinking_llm=self.quick_thinking_llm,
        )
        self.memory_log = TradingMemoryLog(
            memory_dir=self.config.get(
                "project_dir",
                os.path.expanduser("~/.astock_trader"),
            ),
        )

        # ── Build and compile graph ───────────────────────────
        self._emit("graph_build_start", {})
        self.compiled_graph = self.graph_setup.setup_graph(
            selected_analysts=self.selected_analysts,
        )
        self._emit("graph_build_complete", {})

    # ════════════════════════════════════════════════════════════
    #  Public API
    # ════════════════════════════════════════════════════════════

    def propagate(
        self,
        company_name: str,
        trade_date: str,
    ) -> Tuple[Dict[str, Any], str]:
        """Run the full analysis pipeline for a stock on a given date.

        This is the main entry point.  It:
        1. Resolves pending memory entries (optional).
        2. Optionally sets up an SQLite checkpointer.
        3. Invokes the compiled LangGraph.
        4. Logs the state to disk.
        5. Stores the decision in the memory log.
        6. Extracts the trading signal (rating).

        Parameters
        ----------
        company_name : str
            Stock ticker (e.g. ``"000001"``) or company name.
        trade_date : str
            Trade date in ``YYYY-MM-DD`` format.

        Returns
        -------
        tuple[dict, str]
            ``(final_state, rating)`` where *final_state* is the complete
            ``AgentState`` after graph execution and *rating* is the
            extracted Chinese rating string.
        """
        self._emit("propagate_start", {
            "company": company_name,
            "date": trade_date,
        })

        # Resolve pending memory entries
        self._resolve_pending_memory(company_name)

        # Run the graph
        final_state, rating = self._run_graph(company_name, trade_date)

        self._emit("propagate_complete", {
            "company": company_name,
            "date": trade_date,
            "rating": rating,
        })

        return final_state, rating

    # ════════════════════════════════════════════════════════════
    #  Internal: graph execution
    # ════════════════════════════════════════════════════════════

    def _run_graph(
        self,
        company_name: str,
        trade_date: str,
    ) -> Tuple[Dict[str, Any], str]:
        """Execute the LangGraph and handle post-processing."""
        import time

        # ── Past context from memory ──────────────────────────
        past_context = self.memory_log.get_past_context(company_name)

        # ── Initial state ─────────────────────────────────────
        initial_state = self.propagator.create_initial_state(
            company_name=company_name,
            trade_date=trade_date,
            past_context=past_context,
        )

        # ── Checkpointer (optional) ──────────────────────────
        checkpoint_enabled = self.config.get("checkpoint_enabled", False)
        checkpointer = None
        thread_config: Dict[str, Any] = {}

        if checkpoint_enabled:
            try:
                checkpointer = get_checkpointer(company_name)
                tid = thread_id(company_name, trade_date)
                thread_config = {"configurable": {"thread_id": tid}}
                logger.info("Checkpointer enabled: thread=%s", tid)
            except Exception as exc:
                logger.warning("Failed to set up checkpointer: %s", exc)

        # ── Invoke ────────────────────────────────────────────
        graph_args = self.propagator.get_graph_args()

        self._emit("graph_invoke_start", {
            "company": company_name,
            "date": trade_date,
            "recursion_limit": graph_args.get("recursion_limit"),
        })

        t0 = time.time()
        try:
            if checkpointer is not None:
                with checkpointer:
                    final_state = self.compiled_graph.invoke(
                        initial_state,
                        config=thread_config,
                        **graph_args,
                    )
            else:
                final_state = self.compiled_graph.invoke(
                    initial_state,
                    **graph_args,
                )
        except Exception as exc:
            logger.error("Graph invocation failed: %s", exc)
            self._emit("graph_invoke_error", {"error": str(exc)})
            raise
        elapsed = time.time() - t0

        self._emit("graph_invoke_complete", {
            "company": company_name,
            "date": trade_date,
            "elapsed": round(elapsed, 1),
        })

        # ── Patch report with actual elapsed time ─────────────
        report_path = final_state.get("report_path", "")
        if report_path and os.path.isfile(report_path):
            try:
                self._patch_report_elapsed(report_path, elapsed)
            except Exception as exc:
                logger.warning("Failed to patch report elapsed time: %s", exc)

        # ── Log state to disk ─────────────────────────────────
        # Inject elapsed seconds into state for the JSON log
        final_state["_elapsed_seconds"] = round(elapsed, 1)
        self._log_state_to_disk(final_state, company_name, trade_date)

        # ── Extract signal ────────────────────────────────────
        decision_text = final_state.get("final_trade_decision", "")
        rating = self.signal_processor.process_signal(decision_text)

        # ── Store decision in memory ─────────────────────────
        self._store_decision(company_name, trade_date, final_state, rating)

        return final_state, rating

    # ════════════════════════════════════════════════════════════
    #  Internal: LLM creation
    # ════════════════════════════════════════════════════════════

    def _create_llms(self) -> Tuple[Any, Any]:
        """Create deep-thinking and quick-thinking LLM instances."""
        from astock_trader.llm_clients.factory import create_llm_client

        provider = self.config.get("llm_provider", "openai")
        deep_model = self.config.get("deep_think_llm", "deepseek-chat")
        quick_model = self.config.get("quick_think_llm", "deepseek-chat")
        base_url = self.config.get("backend_url")

        # API key resolution: check multiple env vars for compatibility
        api_key = (
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
            or os.environ.get("LLM_API_KEY")
        )

        # Auto-detect DeepSeek base URL when model is deepseek-* and no explicit URL
        if not base_url and "deepseek" in deep_model.lower():
            base_url = "https://api.deepseek.com/v1"

        deep_client = create_llm_client(
            provider=provider,
            model=deep_model,
            base_url=base_url,
            api_key=api_key,
            temperature=0.3,
        )
        quick_client = create_llm_client(
            provider=provider,
            model=quick_model,
            base_url=base_url,
            api_key=api_key,
            temperature=0.3,
        )

        deep_llm = deep_client.get_llm()
        quick_llm = quick_client.get_llm()

        logger.info(
            "LLMs created: deep=%s, quick=%s (provider=%s)",
            deep_model, quick_model, provider,
        )
        return deep_llm, quick_llm

    # ════════════════════════════════════════════════════════════
    #  Internal: logging & memory
    # ════════════════════════════════════════════════════════════

    def _log_state_to_disk(
        self,
        state: Dict[str, Any],
        company_name: str,
        trade_date: str,
    ) -> None:
        """Persist the final state as a JSON log file."""
        results_dir = self.config.get(
            "results_dir",
            os.path.expanduser("~/.astock_trader/logs"),
        )
        Path(results_dir).mkdir(parents=True, exist_ok=True)

        filename = f"{company_name}_{trade_date}_{datetime.now():%Y%m%d_%H%M%S}.json"
        filepath = os.path.join(results_dir, filename)

        # Serialise state — convert messages to dicts, skip non-serialisable
        serialisable = self._make_serialisable(state)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(serialisable, f, ensure_ascii=False, indent=2)
            logger.info("State logged to %s", filepath)
        except Exception as exc:
            logger.warning("Failed to log state: %s", exc)

    def _store_decision(
        self,
        company_name: str,
        trade_date: str,
        state: Dict[str, Any],
        rating: str,
    ) -> None:
        """Store the decision in the trading memory log."""
        decision_record = {
            "rating": rating,
            "action": self._extract_action(state),
            "final_trade_decision": state.get("final_trade_decision", "")[:500],
            "reasoning": state.get("investment_plan", "")[:300],
        }

        try:
            self.memory_log.store_decision(
                ticker=company_name,
                trade_date=trade_date,
                final_decision=decision_record,
            )
        except Exception as exc:
            logger.warning("Failed to store decision in memory: %s", exc)

    def _resolve_pending_memory(self, company_name: str) -> None:
        """Attempt to resolve pending memory entries with reflections.

        For each pending entry, we would ideally fetch the actual return
        and generate a reflection.  In the current implementation this is
        a no-op placeholder; actual resolution requires external data
        (e.g. a cron job that checks returns after N days).
        """
        try:
            pending = self.memory_log.get_pending_entries()
            if pending:
                logger.debug(
                    "Found %d pending memory entries for resolution.",
                    len(pending),
                )
                # TODO: Implement automatic resolution with actual returns
        except Exception as exc:
            logger.debug("Memory resolution check skipped: %s", exc)

    # ════════════════════════════════════════════════════════════
    #  Internal: helpers
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _patch_report_elapsed(filepath: str, elapsed: float) -> None:
        """Patch the HTML report file with the actual elapsed time."""
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        # Replace the placeholder elapsed value (0) in the embedded JSON
        html = html.replace(
            '"elapsed": 0',
            f'"elapsed": {round(elapsed, 1)}',
            1,
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.debug("Patched report elapsed: %.1fs in %s", elapsed, filepath)

    @staticmethod
    def _extract_action(state: Dict[str, Any]) -> str:
        """Try to extract the trade action from the trader's plan."""
        plan = state.get("trader_investment_plan", "")
        for action in ("买入", "增持", "持有", "减持", "卖出"):
            if action in plan:
                return action
        return "unknown"

    @staticmethod
    def _make_serialisable(obj: Any) -> Any:
        """Recursively convert an object tree into a JSON-serialisable form."""
        if isinstance(obj, dict):
            return {k: TradingAgentsGraph._make_serialisable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [TradingAgentsGraph._make_serialisable(item) for item in obj]
        # LangChain messages
        if hasattr(obj, "content") and hasattr(obj, "type"):
            return {
                "type": getattr(obj, "type", "unknown"),
                "content": getattr(obj, "content", ""),
                "name": getattr(obj, "name", None),
            }
        # Fallback
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """Fire all registered callbacks with the given event."""
        for cb in self.callbacks:
            try:
                cb(event, data)
            except Exception as exc:
                logger.debug("Callback error on '%s': %s", event, exc)
