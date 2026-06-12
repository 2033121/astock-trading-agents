# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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

[0.3.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.3.0
[0.1.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.1.0
