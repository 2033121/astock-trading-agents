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
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from astock_trader.agents.utils.memory import TradingMemoryLog
from astock_trader.default_config import DEFAULT_CONFIG
from astock_trader.graph.checkpointer import (
    get_checkpointer,
    thread_id,
)
from astock_trader.graph.conditional_logic import ConditionalLogic
from astock_trader.graph.propagation import Propagator
from astock_trader.graph.reflection import Reflector
from astock_trader.graph.setup import GraphSetup
from astock_trader.graph.signal_processing import SignalProcessor
from astock_trader.llm_clients.resilience import ResilientInvoker

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
#  Model-name → base_url auto-detection map
#  When tiers use different models/providers, each gets its own endpoint.
# ────────────────────────────────────────────────────────────────
_MODEL_PREFIX_MAP: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "mimo": "https://api.xiaomimimo.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
}


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
        selected_analysts: list[str] | None = None,
        debug: bool = False,
        config: dict[str, Any] | None = None,
        callbacks: list[Callable] | None = None,
    ) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.selected_analysts = selected_analysts or ["market", "social", "news", "fundamentals"]
        self.debug = debug
        self.callbacks = callbacks or []

        # ── Create LLM clients (4-tier) ──────────────────────
        self.deep_thinking_llm, self.heavy_thinking_llm, self.standard_thinking_llm, self.quick_thinking_llm = (
            self._create_llms()
        )

        # ── Sub-components ────────────────────────────────────
        self.invoker = ResilientInvoker(
            max_retries=self.config.get("llm_max_retries", 3),
            base_delay=self.config.get("llm_retry_base_delay", 4),
            max_delay=self.config.get("llm_retry_max_delay", 60),
            cb_threshold=self.config.get("circuit_breaker_threshold", 5),
            cb_cooldown=self.config.get("circuit_breaker_cooldown", 30),
        )

        # ── Activate Headroom compression (Library mode) ─────
        # Windows 上 ONNX Runtime 不兼容 Kompress int8-wo 模型，自动降级关闭。
        from astock_trader.llm_clients.resilience import configure_headroom
        _headroom_enabled = self.config.get("enable_headroom_compression", False)
        if _headroom_enabled:
            import sys as _sys
            if _sys.platform == "win32":
                _logger = logging.getLogger("astock_trader.headroom")
                _logger.warning(
                    "Headroom compression is not supported on Windows "
                    "(ONNX Runtime MatMulNBits 仅支持 4-bit，Kompress 需要 8-bit)。"
                    "已自动禁用。如需使用请在 macOS/Linux 上运行。"
                )
                _headroom_enabled = False
        configure_headroom(
            enable=_headroom_enabled,
            min_tokens=self.config.get("headroom_min_tokens", 500),
        )

        self.logic = ConditionalLogic(
            max_debate_rounds=self.config.get("max_debate_rounds", 1),
            max_risk_discuss_rounds=self.config.get("max_risk_discuss_rounds", 1),
        )
        self.graph_setup = GraphSetup(
            deep_thinking_llm=self.deep_thinking_llm,
            heavy_thinking_llm=self.heavy_thinking_llm,
            standard_thinking_llm=self.standard_thinking_llm,
            quick_thinking_llm=self.quick_thinking_llm,
            conditional_logic=self.logic,
            language=self.config.get("output_language", "Chinese"),
            report_output_dir=self.config.get("report_output_dir", ""),
            invoker=self.invoker,
            context_slimming=self.config.get("enable_context_slimming", True),
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

        # ── Vector memory (optional) ─────────────────────────
        self.market_memory = None
        if self.config.get("enable_vector_memory", True):
            try:
                from astock_trader.memory.market_memory import MarketMemory
                mem_dir = self.config.get("vector_memory_dir") or os.path.join(
                    self.config.get("project_dir", os.path.expanduser("~/.astock_trader")),
                    "vector_memory",
                )
                self.market_memory = MarketMemory(
                    backend=self.config.get("vector_memory_backend", "auto"),
                    persist_dir=mem_dir,
                )
                self.market_memory.load()
                logger.info(
                    "MarketMemory initialised: %d records indexed.",
                    self.market_memory.record_count,
                )
            except Exception as exc:
                logger.warning("MarketMemory init failed: %s", exc)
                self.market_memory = None

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
    ) -> tuple[dict[str, Any], str]:
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
        self._emit(
            "propagate_start",
            {
                "company": company_name,
                "date": trade_date,
            },
        )

        # Resolve pending memory entries
        self._resolve_pending_memory(company_name)

        # Run the graph
        final_state, rating = self._run_graph(company_name, trade_date)

        self._emit(
            "propagate_complete",
            {
                "company": company_name,
                "date": trade_date,
                "rating": rating,
            },
        )

        return final_state, rating

    # ════════════════════════════════════════════════════════════
    #  Internal: graph execution
    # ════════════════════════════════════════════════════════════

    def _run_graph(
        self,
        company_name: str,
        trade_date: str,
    ) -> tuple[dict[str, Any], str]:
        """Execute the LangGraph and handle post-processing."""
        import time

        # ── Past context from memory ──────────────────────────
        past_context = self.memory_log.get_past_context(company_name)

        # Enrich with vector memory search (if available)
        if self.market_memory and self.market_memory.record_count > 0:
            try:
                query = f"{company_name} 分析 投资"
                records = self.market_memory.search(query, top_k=3)
                memory_context = self.market_memory.format_for_prompt(records)
                if memory_context:
                    past_context = f"{past_context}\n\n{memory_context}" if past_context else memory_context
                    logger.info(
                        "Vector memory: injected %d historical records into context.",
                        len(records),
                    )
            except Exception as exc:
                logger.debug("Vector memory search failed: %s", exc)

        # ── Initial state ─────────────────────────────────────
        initial_state = self.propagator.create_initial_state(
            company_name=company_name,
            trade_date=trade_date,
            past_context=past_context,
        )

        # ── Checkpointer (optional) ──────────────────────────
        checkpoint_enabled = self.config.get("checkpoint_enabled", False)
        checkpointer = None
        thread_config: dict[str, Any] = {}

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

        self._emit(
            "graph_invoke_start",
            {
                "company": company_name,
                "date": trade_date,
                "recursion_limit": graph_args.get("recursion_limit"),
            },
        )

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

        self._emit(
            "graph_invoke_complete",
            {
                "company": company_name,
                "date": trade_date,
                "elapsed": round(elapsed, 1),
            },
        )

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

        # ── Index in vector memory ───────────────────────────
        self._index_in_memory(company_name, trade_date, final_state, rating)

        return final_state, rating

    # ════════════════════════════════════════════════════════════
    #  Internal: LLM creation
    # ════════════════════════════════════════════════════════════

    def _create_llms(self) -> tuple[Any, Any, Any, Any]:
        """Create deep / heavy / standard / quick LLM instances (4-tier).

        Each tier can use a different model and provider.  When ``backend_url``
        is not set, the base URL is auto-resolved **per model** so that e.g.
        ``mimo-v2.5-pro`` routes to the MiMo API while ``deepseek-v4-flash``
        routes to DeepSeek.

        Returns
        -------
        tuple[deep_llm, heavy_llm, standard_llm, quick_llm]
        """
        from astock_trader.llm_clients.factory import (
            _PROVIDER_BASE_URLS,
            create_llm_client,
        )

        provider = self.config.get("llm_provider", "deepseek")
        deep_model = self.config.get("deep_think_llm", "deepseek-chat")
        heavy_model = self.config.get(
            "heavy_think_llm",
            self.config.get("deep_think_llm", "deepseek-chat"),
        )
        standard_model = self.config.get(
            "standard_think_llm",
            self.config.get("deep_think_llm", "deepseek-chat"),
        )
        quick_model = self.config.get("quick_think_llm", "deepseek-chat")
        explicit_url = self.config.get("backend_url")

        # API key resolution: check multiple env vars for compatibility
        api_key = (
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
            or os.environ.get("MIMO_API_KEY")
            or os.environ.get("LLM_API_KEY")
        )

        def _resolve(model: str) -> tuple[str, str | None]:
            """Return (provider, base_url) for a model name.

            If the user set an explicit ``backend_url``, use it for all tiers.
            Otherwise, auto-detect from the model name.
            """
            if explicit_url:
                return provider, explicit_url
            low = model.lower()
            for prefix, url in _MODEL_PREFIX_MAP.items():
                if low.startswith(prefix):
                    return prefix, url
            # Fallback to the global provider
            return provider, _PROVIDER_BASE_URLS.get(provider)

        deep_prov, deep_url = _resolve(deep_model)
        heavy_prov, heavy_url = _resolve(heavy_model)
        std_prov, std_url = _resolve(standard_model)
        quick_prov, quick_url = _resolve(quick_model)

        def _resolve_api_key(prov: str) -> str:
            """Return the API key appropriate for *prov*.

            Each provider has its own environment variable (e.g. MIMO_API_KEY
            for the ``mimo`` provider).  Falls back to the generic resolution
            chain so single-provider setups keep working unchanged.
            """
            _PROVIDER_KEY_ENV: dict[str, str] = {
                "deepseek": "DEEPSEEK_API_KEY",
                "mimo": "MIMO_API_KEY",
                "qwen": "DASHSCOPE_API_KEY",
                "dashscope": "DASHSCOPE_API_KEY",
                "glm": "GLM_API_KEY",
                "zhipu": "GLM_API_KEY",
                "openai": "OPENAI_API_KEY",
                "siliconflow": "SILICONFLOW_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "together": "TOGETHER_API_KEY",
                "groq": "GROQ_API_KEY",
            }
            env_var = _PROVIDER_KEY_ENV.get(prov.lower())
            if env_var:
                key = os.environ.get(env_var)
                if key:
                    return key
            # Fallback to the general resolution chain
            return api_key or ""

        deep_client = create_llm_client(
            provider=deep_prov, model=deep_model,
            base_url=deep_url, api_key=_resolve_api_key(deep_prov), temperature=0.3,
        )
        heavy_client = create_llm_client(
            provider=heavy_prov, model=heavy_model,
            base_url=heavy_url, api_key=_resolve_api_key(heavy_prov), temperature=0.3,
        )
        standard_client = create_llm_client(
            provider=std_prov, model=standard_model,
            base_url=std_url, api_key=_resolve_api_key(std_prov), temperature=0.3,
        )
        quick_client = create_llm_client(
            provider=quick_prov, model=quick_model,
            base_url=quick_url, api_key=_resolve_api_key(quick_prov), temperature=0.3,
        )

        deep_llm = deep_client.get_llm()
        heavy_llm = heavy_client.get_llm()
        standard_llm = standard_client.get_llm()
        quick_llm = quick_client.get_llm()

        logger.info(
            "LLMs created (4-tier): deep=%s@%s, heavy=%s@%s, standard=%s@%s, quick=%s@%s",
            deep_model, deep_prov,
            heavy_model, heavy_prov,
            standard_model, std_prov,
            quick_model, quick_prov,
        )
        return deep_llm, heavy_llm, standard_llm, quick_llm

    # ════════════════════════════════════════════════════════════
    #  Internal: logging & memory
    # ════════════════════════════════════════════════════════════

    def _log_state_to_disk(
        self,
        state: dict[str, Any],
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
        state: dict[str, Any],
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

    def _index_in_memory(
        self,
        company_name: str,
        trade_date: str,
        state: dict[str, Any],
        rating: str,
    ) -> None:
        """Index the analysis result in vector memory for future retrieval."""
        if self.market_memory is None:
            return

        try:
            parts = []
            for field in [
                "market_report", "sentiment_report",
                "news_report", "fundamentals_report",
            ]:
                value = state.get(field, "")
                if value:
                    parts.append(value)

            decision = state.get("final_trade_decision", "")
            if decision:
                parts.append(decision)

            if parts:
                content = "\n\n".join(parts)
                self.market_memory.index_analysis(
                    ticker=company_name,
                    date=trade_date,
                    content=content,
                    rating=rating,
                )
                self.market_memory.save()
        except Exception as exc:
            logger.debug("Failed to index in vector memory: %s", exc)

    def _resolve_pending_memory(self, company_name: str) -> None:
        """Resolve pending memory entries that are ≥5 days old.

        For each eligible entry:
        1. Fetch actual T+5 return via akshare.
        2. Fetch benchmark (CSI 300) return for alpha calculation.
        3. Generate LLM reflection via Reflector.
        4. Batch-update the memory log (pending → resolved).

        Errors on individual entries are logged and skipped so that one
        bad ticker doesn't block the entire batch.
        """
        from datetime import datetime, timedelta

        try:
            pending = self.memory_log.get_pending_entries()
            if not pending:
                return

            cutoff = datetime.now() - timedelta(days=5)
            eligible: list[dict[str, Any]] = []
            for entry in pending:
                try:
                    entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
                    if entry_date <= cutoff:
                        eligible.append(entry)
                except (ValueError, KeyError):
                    continue

            if not eligible:
                logger.debug(
                    "No pending entries old enough to resolve (%d pending, cutoff=%s).",
                    len(pending),
                    cutoff.strftime("%Y-%m-%d"),
                )
                return

            logger.info("Resolving %d pending memory entries (≥5 days old).", len(eligible))

            updates: list[dict[str, Any]] = []
            for entry in eligible:
                ticker = entry["ticker"]
                trade_date = entry["date"]
                decision_text = ""
                decision = entry.get("decision", {})
                if isinstance(decision, dict):
                    decision_text = decision.get("final_trade_decision", "") or decision.get("reasoning", "")

                try:
                    raw_ret = self._fetch_actual_returns(ticker, trade_date, days=5)
                    bench_ret = self._fetch_benchmark_return(trade_date, days=5)

                    if raw_ret is None:
                        logger.debug("Could not fetch returns for %s, skipping.", ticker)
                        continue

                    alpha = (raw_ret - bench_ret) if bench_ret is not None else 0.0

                    reflection_text = self.reflector.reflect_on_final_decision(
                        final_decision=decision_text or f"评级: {entry.get('rating', '?')}",
                        raw_return=raw_ret,
                        alpha_return=alpha,
                    )

                    updates.append({
                        "ticker": ticker,
                        "trade_date": trade_date,
                        "reflection": {
                            "outcome": f"5日收益 {raw_ret:+.1%}, 超额 {alpha:+.1%}",
                            "raw_return": round(raw_ret, 4),
                            "alpha_return": round(alpha, 4),
                            "lesson": reflection_text,
                            "resolved_date": datetime.now().strftime("%Y-%m-%d"),
                        },
                    })
                    logger.info(
                        "Resolved %s@%s: raw=%.1f%%, alpha=%.1f%%",
                        ticker, trade_date, raw_ret * 100, alpha * 100,
                    )
                except Exception as exc:
                    logger.warning("Failed to resolve entry %s@%s: %s", ticker, trade_date, exc)
                    continue

            if updates:
                count = self.memory_log.batch_update_with_outcomes(updates)
                logger.info("Reflection complete: %d/%d entries resolved.", count, len(updates))

        except Exception as exc:
            logger.warning("Memory resolution failed: %s", exc)

    def _fetch_actual_returns(
        self,
        ticker: str,
        trade_date: str,
        days: int = 5,
    ) -> float | None:
        """Fetch actual stock return over *days* trading days after *trade_date*.

        Uses akshare ``stock_zh_a_hist`` with forward-fill adjustment.
        Returns ``None`` if data is unavailable or insufficient.
        """
        try:
            import akshare as ak
            from datetime import datetime, timedelta

            dt = datetime.strptime(trade_date, "%Y-%m-%d")
            start_str = dt.strftime("%Y%m%d")
            end_str = (dt + timedelta(days=days + 10)).strftime("%Y%m%d")

            df = ak.stock_zh_a_hist(
                symbol=ticker, period="daily",
                start_date=start_str, end_date=end_str,
                adjust="qfq",
            )
            if df is None or df.empty or len(df) < 2:
                return None

            df["日期"] = df["日期"].astype(str)
            df = df[df["日期"] >= trade_date].reset_index(drop=True)
            if len(df) < 2:
                return None

            entry_price = float(df.iloc[0]["收盘"])
            target_idx = min(days, len(df) - 1)
            exit_price = float(df.iloc[target_idx]["收盘"])

            if entry_price <= 0:
                return None
            return (exit_price - entry_price) / entry_price

        except ImportError:
            logger.debug("akshare not available for return fetching.")
            return None
        except Exception as exc:
            logger.debug("Failed to fetch actual returns for %s: %s", ticker, exc)
            return None

    def _fetch_benchmark_return(
        self,
        trade_date: str,
        days: int = 5,
    ) -> float | None:
        """Fetch CSI 300 benchmark return over *days* trading days.

        Uses akshare ``index_zh_a_hist`` for the 沪深300 index (000300).
        Returns ``None`` if data is unavailable.
        """
        try:
            import akshare as ak
            from datetime import datetime, timedelta

            dt = datetime.strptime(trade_date, "%Y-%m-%d")
            start_str = dt.strftime("%Y%m%d")
            end_str = (dt + timedelta(days=days + 10)).strftime("%Y%m%d")

            df = ak.index_zh_a_hist(
                symbol="000300", period="daily",
                start_date=start_str, end_date=end_str,
            )
            if df is None or df.empty or len(df) < 2:
                return None

            df["日期"] = df["日期"].astype(str)
            df = df[df["日期"] >= trade_date].reset_index(drop=True)
            if len(df) < 2:
                return None

            entry_price = float(df.iloc[0]["收盘"])
            target_idx = min(days, len(df) - 1)
            exit_price = float(df.iloc[target_idx]["收盘"])

            if entry_price <= 0:
                return None
            return (exit_price - entry_price) / entry_price

        except ImportError:
            logger.debug("akshare not available for benchmark return.")
            return None
        except Exception as exc:
            logger.debug("Failed to fetch benchmark return: %s", exc)
            return None

    # ════════════════════════════════════════════════════════════
    #  Internal: helpers
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _patch_report_elapsed(filepath: str, elapsed: float) -> None:
        """Patch the HTML report file with the actual elapsed time."""
        with open(filepath, encoding="utf-8") as f:
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
    def _extract_action(state: dict[str, Any]) -> str:
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

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        """Fire all registered callbacks with the given event."""
        for cb in self.callbacks:
            try:
                cb(event, data)
            except Exception as exc:
                logger.debug("Callback error on '%s': %s", event, exc)
