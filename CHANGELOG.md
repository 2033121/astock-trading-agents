# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-06-16

### Added

- **Backtest Feedback Consumer** (`agents/utils/backtest_consumer.py`, 258 lines):
  - `BacktestFeedbackConsumer` class: reads `backtest_feedback.json`, validates schema/expiry/quality gates
  - Per-agent getters with character-budget truncation at sentence boundaries: analysts (120), debaters (100), manager (100), risk (80), PM (150)
  - Three-tier feedback decay: fresh (<90d, 1.0x weight) → warning (90–180d, 0.5x + "衰减中" notice) → expired (>180d, auto-ignore)
  - `decay_state` / `age_days` / `quality_info` properties for logging and debugging
  - Quality gates: `min_total_verified=10`, `schema_version=1`, configurable `decay_warn_days` / `decay_ignore_days`

- **复盘深度分析 Expert Suite Skill** (`skills/复盘深度分析/SKILL.md`):
  - 7-step flow: read snapshots → statistics → quality gate → LLM deep analysis → JSON output → verify → report
  - Outputs `backtest_feedback.json` matching consumer contract (schema_version=1)
  - Integrated into weekly Friday 17:00 cron job alongside `review_backtest.py`

### Fixed

- **past_context Injection Asymmetry** (`graph/setup.py`):
  - Added missing `past_context` to Bear Researcher, Research Manager, Portfolio Manager
  - Added missing `trade_date` to 3 risk analysts (Aggressive/Conservative/Neutral)
  - Root cause: only Bull Researcher and 4 analysts had injection; debate opponent and judge were blind

- **Tracking Interval Calculation** (plugin `scripts/review_backtest.py`):
  - T+N now counts **trading days** instead of calendar days via sorted trading-day index
  - Price data window expanded from 30 to 45 calendar days to cover T+20 trading days
  - Previously T+5/T+10/T+20 collapsed onto adjacent dates due to weekend/holiday gaps

- **Memory Rotation Never Called** (`graph/trading_graph.py`):
  - Added `_apply_rotation()` call after `_store_decision()` to prevent unbounded memory growth
  - Configurable via `enable_memory_rotation`, `memory_rotation_max_same`, `memory_rotation_max_cross`

### Changed

- **Snapshot Confidence Field** (plugin `scripts/save_snapshot.py`):
  - New `confidence: float` field derived from debate consensus (高=0.9, 中=0.6, 低=0.3, absent=0.5)
  - Available for future weighted feedback injection (high-confidence snapshots carry more weight)

- **Prompt Injection Pipeline** (`graph/setup.py`, `graph/trading_graph.py`):
  - All 10 pipeline nodes now receive conditional backtest feedback via `_bt_feedback()` helper
  - `GraphSetup.__init__()` accepts `backtest_consumer` parameter
  - Consumer auto-initialises from config; gracefully degrades to no-op when file missing

- **Default Config** (`default_config.py`):
  - New keys: `enable_backtest_feedback`, `backtest_feedback_path`, `backtest_feedback_min_verified` (10), `backtest_feedback_expiry_days` (90), `backtest_feedback_decay_warn_days` (90), `backtest_feedback_decay_ignore_days` (180), `enable_memory_rotation`, `memory_rotation_max_same` (10), `memory_rotation_max_cross` (10)

### Testing

- 185 total tests (151 original + 34 backtest consumer tests)
- `test_backtest_consumer.py`: 34 tests across 8 classes (loading, quality gate, schema, expiry, getters, truncation, quality info, decay tiers)

## [0.3.0] - 2026-06-13

### Added

- **LLM Resilience Layer** (`llm_clients/resilience.py`):
  - `ResilientInvoker` wrapping 8 non-ReAct `llm.invoke()` calls with Tenacity retry (3x exponential backoff 4s→60s) + 3-state circuit breaker (5 failures → OPEN → 30s cooldown)
  - `_safe_invoke()` graceful degradation to raw invoke when circuit breaker is open
  - Headroom v0.25.0 Library mode integration: `_compress_messages()` compresses messages before LLM calls, saving 60-95% tokens on long prompts
  - Configurable via `llm_max_retries`, `circuit_breaker_threshold`, `circuit_breaker_cooldown`, `enable_headroom_compression`, `headroom_min_tokens`

- **Analyst Structured Output** (`agents/schemas.py`):
  - 5 Pydantic v2 models: `MarketSignal`, `SentimentSignal`, `NewsSignal`, `FundamentalSignal`, `AnalystConsensus`
  - 4 robust parsers: JSON → markdown block → brace matching + CJK/EN aliases → free-text regex fallback

- **Four-Tier Model Allocation** (`graph/setup.py`):
  - New `heavy_think_llm` config key; 4 tiers: Deep (PM only) → Heavy (bull/bear debate) → Standard (research mgr + trader + 3 risk) → Quick (4 analysts + auxiliary)
  - Each tier independently auto-routes to the correct LLM provider via `_MODEL_PREFIX_MAP`

- **Reflection Loop** (`graph/trading_graph.py`):
  - `_resolve_pending_memory()`: filters ≥5-day pending entries → `_fetch_actual_returns()` via akshare → `_fetch_benchmark_return()` (CSI300) → Reflector generates LLM reflection → `batch_update_with_outcomes()` writes back to memory

- **Smart Backtesting** (`scripts/review_backtest.py`):
  - Multi-dimensional scoring: direction (40%) + magnitude (25%) + timing (15%) + assumption validation (20%)
  - `recognize_patterns()`: detects rating bias, magnitude bias, direction bias
  - `generate_strategy_feedback()`: actionable feedback for prompt injection

- **Context Slimming** (`graph/context_slimmer.py`):
  - Per-node report trimming: PM keeps conclusions (~60-70% compression), risk keeps risk paragraphs (~40-50%), researchers keep evidence (~20-30%), trader no trimming
  - `_gather_reports_for(state, target_node)` replaces all 8 `_gather_reports()` calls
  - Configurable via `enable_context_slimming` (default: True)

- **Vector Memory** (`memory/market_memory.py`):
  - Pure Python TF-IDF bigram engine (ChromaDB optional)
  - `AnalysisRecord` dataclass + `_TfIdfIndex` backend + `MarketMemory` public API
  - Pre-analysis: semantic search top-3 injected into prompt; Post-analysis: auto-indexed with pickle+JSON persistence
  - Configurable via `enable_vector_memory`, `vector_memory_backend`, `vector_memory_dir`

### Changed

- `GraphSetup.__init__()` now accepts `context_slimming` parameter
- `_create_llms()` returns 4-tuple (deep, heavy, standard, quick) instead of 3-tuple
- `default_config.py`: added `heavy_think_llm`, resilience config keys, headroom config, context slimming, vector memory config

### Testing

- 276 total tests (151 original + 125 new phase tests)
- `test_phase1.py`: 16 tests (resilience, schemas, parsers, config)
- `test_phase2.py`: 60 tests (4-tier models, reflection, snapshots, backtesting)
- `test_phase3.py`: 49 tests (context slimming, vector memory, pipeline integration)

## [0.1.0] - 2026-06-10

### Added

- **Core Pipeline**: LangGraph-based multi-agent analysis framework with 15 AI roles
  - 4 parallel analysts (market, news, social media, fundamentals) with ReAct tool loops
  - Bull/Bear investment debate with configurable rounds
  - Research Manager synthesizing debate into structured investment plan
  - Trader converting plans into executable trading strategies
  - 3-way risk debate (aggressive/conservative/neutral) with configurable rounds
  - Portfolio Manager producing final investment decision
  - Report Generator creating interactive HTML reports
- **Multi-Source Data Layer**: 3-level vendor fallback system
  - akshare for market data and technical indicators
  - Tushare Pro for financial statements and capital flow
  - EastMoney MX for news and real-time quotes
- **5-Level Rating System**: 买入/增持/持有/减持/卖出 with structured extraction
- **Decision Memory**: Trading memory log with pending/resolved lifecycle and delayed reflection
- **LLM Flexibility**: OpenAI-compatible client supporting 9 providers (OpenAI, DeepSeek, Qwen, GLM, Ollama, OpenRouter, SiliconFlow, Together, Groq)
- **CLI**: Typer-based CLI with analyze, history, memory, and config commands
- **QoderWork Plugin**: 4 integrated skills (智能分析, 分析历史, 决策记忆, 交易配置)
- **AI Editor Integration**: Project instructions for Claude Code (`CLAUDE.md`), OpenAI Codex (`AGENTS.md`), and Trae IDE (`.trae/rules/`)
- **Testing**: 151 unit tests covering schemas, conditional logic, signal processing, memory, data routing, and agent factories

[0.4.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.4.0
[0.3.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.3.0
[0.1.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.1.0
