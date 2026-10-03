# AStock Trading Agents — Project Instructions

A-share multi-agent quantitative trading decision framework based on LangGraph. 15 AI agent roles collaborate through structured debate to produce investment ratings.

> 面向「在各种 Agent 宿主里使用本框架」的完整说明见 `docs/Agent接入指南.md`；
> 本文件是**给在本仓库里写代码的 agent** 看的项目约定。

## Quick Commands

```bash
# Install
pip install -e .

# Run analysis (2-8 min, consumes real tokens)
astock-trader analyze 600519 --date 2026-06-10 --provider deepseek

# Machine-readable: JSON on stdout (this is what the MCP server uses)
astock-trader analyze 000155 --quiet --output -

# Monitor / watchlist
astock-trader watch 600519 000001 --once

# Run tests
pytest tests/                     # 799 tests
python -m ruff check src/ tests/ mcp_server.py
python -m ruff format --check src/ tests/ mcp_server.py

# View config
astock-trader config --show
```

## Project Structure

- `src/astock_trader/agents/` — 15 AI agent definitions (analysts, researchers, managers, trader, risk analysts)
  - `analysts/` — 4 parallel analysts: market, news, social_media, fundamentals
  - `researchers/` — bull/bear researchers for investment debate
  - `managers/` — research_manager (synthesizes debate) + portfolio_manager (final decision)
  - `trader/` — converts investment plan to executable trading strategy
  - `risk_mgmt/` — aggressive/conservative/neutral risk debaters
  - `utils/` — agent_states.py (AgentState), memory.py, rating.py, data tool wrappers
- `src/astock_trader/dataflows/` — Multi-source data layer
  - `interface.py` — **per-method** vendor routing table (`VENDOR_METHODS`); falls back on
    exception *or* an `"[ERROR] ..."` soft-failure string
  - `akshare_data.py` — OHLCV (东方财富 → 新浪 → 腾讯 three-source fallback) + technical indicators
  - `tushare_data.py` — Financial statements, capital flow, shareholder info
  - `mx_data.py` — EastMoney MX news
  - `eastmoney_news.py` — News + block trades (大宗交易)
  - `realtime_data.py` — Realtime quotes for the monitor layer (Tencent primary / Sina fallback)
  - `symbols.py` — Symbol format conversions (`600519` ↔ `sh600519` ↔ `600519.SH`)
- `src/astock_trader/graph/` — LangGraph orchestration
  - `setup.py` — Graph construction, node factories, edge routing, `_merge_debate()`
  - `trading_graph.py` — Main orchestrator, API key resolution, elapsed tracking, config push
  - `report_generator.py` — Deterministic HTML report generator (no LLM call)
  - `signal_processing.py` — Rating extraction from decision text
  - `propagation.py` — Initial state factory
- `src/astock_trader/monitor/` — Decoupled watch layer (rules DSL / polling engine / store / notifier). **No LLM, no LangGraph** — it only knows "quote dict → event"
- `src/astock_trader/llm_clients/` — LLM client abstraction (9 providers via OpenAI-compatible API)
- `src/astock_trader/external_calibration/` — Third-party scoreboard ledger (physically isolated from internal memory)
- `src/astock_trader/paths.py` — **Single source of truth for the project root**; every output dir derives from it
- `src/astock_trader/cli/` — Typer CLI (analyze / watch / history / memory / config)
- `mcp_server.py` — Zero-dependency MCP stdio server (5 tools)
- `skills/` — 7 agent-invocable workflows (SKILL.md per directory)
- `tests/` — pytest test suite (799 tests, 15 skipped by environment)

## Pipeline Topology

```
START → 4 Analysts (parallel) → Bull/Bear Debate → Research Manager
→ Trader → Risk Debate (aggressive→conservative→neutral)
→ Portfolio Manager → Report Generator → END
```

## Key Patterns

- **Agent factory functions** return LangChain Runnable objects; node factories in `setup.py` create closures capturing config
- **AgentState** uses `MessagesState` with `add_messages` reducer
- **⚠ Nested reducers do NOT work.** `investment_debate_state` / `risk_debate_state` are
  nested TypedDicts; the `Annotated[list, _append_str_list]` annotations on their sub-fields are
  **inert** — LangGraph treats the whole sub-dict as a LastValue channel and *replaces* it on write.
  Debate order is Bull → Bear → Bull(rebut) → Research Manager, so without a fix the manager would
  only ever see the last bull turn and `bear_history` would be gone (this actually happened: the
  manager wrote "本次空头未提交论据" and drafted a substitute bear case).
  **Every debate node must write through `setup._merge_debate()`**, which emits the merged full dict.
  Guarded by `tests/test_debate_state_merge.py`.
- **ReAct empty message fix**: `setup.py._create_llm_agent()` injects SystemMessage + HumanMessage when messages list is empty. Msg-clear uses `RemoveMessage` and warns when a message has no `id` (an un-cleared message leaks the previous analyst's system prompt into the next one).
- **Report Generator**: deterministic node (no LLM), runs inside graph. Elapsed time is patched
  post-graph into **two** places: the JSON `elapsed` field and the summary prose (which uses
  `ELAPSED_PLACEHOLDER`).
- **Data vendor fallback**: per-**method** chains in `interface.py::VENDOR_METHODS` (e.g.
  `get_global_news: mx → eastmoney → gdelt`). The `data_vendors` per-category config block is
  currently **not consumed** — don't assume it drives routing.
- **Config must be pushed to the data layer**: `TradingAgentsGraph.__init__` calls
  `dataflows.config.set_config(self.config)`. Without it `get_config()` returns `{}` and
  credentials in `user_config.json` never reach the vendors (silent failure — this happened).
- **Credit precedence is config-first**: `api_key` and `tushare_token` resolve
  **user_config.json → environment variable**. Deliberately: a stale env var otherwise shadows
  a freshly configured value, which is exactly what produced rounds of "token 失效" reports.
- **Rating/action extraction is negation-aware**: `rating.extract_rating()` and
  `rating.extract_action()` scan by **position of first un-negated mention**, not by scale order.
  Naive substring scanning reads 「低估值不是买入充分条件」 as a BUY rating.
- **Tool wrappers must mirror vendor signatures**: a wrapper exposing `(symbol, start_date,
  end_date)` against a vendor taking `(symbol, indicator, curr_date)` raises `TypeError` at call
  time. Guarded structurally by `tests/test_tool_signatures.py` (InjectedState params excluded).
- **Rating system**: 5-level (买入/增持/持有/减持/卖出), extracted from portfolio manager's
  decision text; unparseable → `待复核`, never silently defaulted to 持有.

## Coding Conventions

- Python 3.10+, use type hints everywhere
- Docstrings in English (Google style); analysis output in Chinese
- snake_case for functions/variables, PascalCase for classes
- CLI uses Typer with Rich for terminal rendering
- All API keys/tokens via environment variables or `user_config.json` (repo-external), NEVER hardcode or commit them
- State mutations through reducer functions only
- Log messages in English via `logging` module
- Comments explain **why**, not what; match the surrounding density

## Paths

Never hardcode `~/.astock_trader`. Resolve the root:

```python
from astock_trader.paths import project_dir, project_path
```

Resolution: `ASTOCK_HOME` → `D:\astock_trader` (Windows with a D drive) → `~/.astock_trader`.
`default_config.derive_paths()` makes `logs/` `reports/` `memory/` etc. follow `project_dir`.

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `MIMO_API_KEY` / `LLM_API_KEY` | Yes (one of) | LLM authentication; also settable via `config --set api_key` |
| `TUSHARE_TOKEN` | Recommended | Tushare Pro financial data; also settable via `config --set tushare_token` |
| `MX_APIKEY` | Optional | EastMoney MX news data |
| `ASTOCK_HOME` | Optional | Project root override (all output dirs derive from it) |
| `ASTOCK_REPORT_DIR` | Optional | HTML report dir; defaults to `<root>/reports` |
| `ASTOCK_SNAPSHOT_LOG_PATH` | Optional | Snapshot ledger path (used by the MCP server) |
| `ASTOCK_MCP_CLI_TIMEOUT` | Optional | MCP subprocess timeout, default 1200s |

## Data Sources

- **Tushare Pro**: Financial statements, capital flow, shareholder data, block trades
- **akshare**: Market data (东方财富 → 新浪 → 腾讯), technical indicators, news
- **EastMoney MX**: News, real-time quotes
- **GDELT**: Global news (third fallback for `get_global_news`)

OHLCV units are normalised to `volume(手) / turnover(元)`; the serving source is written into the
tool output header. 前复权 base differs slightly between sources, so one series always comes from
one source (no cross-source splicing).

## Testing

```bash
pytest tests/                                                 # All
pytest tests/ -v                                              # Verbose
pytest tests/ --cov=astock_trader --cov-report=term-missing   # Coverage
```

Regression guards worth knowing about (they catch *silent* failures):

| Test file | Guards |
|-----------|--------|
| `test_tool_signatures.py` | Tool wrapper vs vendor parameter names |
| `test_debate_state_merge.py` | Debate history not overwritten by nested-state replacement |
| `test_dataflows_config_wiring.py` | Config actually reaches the data layer; credential precedence |
| `test_ohlcv_fallback.py` | Three-source fallback + unit normalisation |
| `test_rating_action.py` | Negation handling in rating/action extraction |
| `test_paths.py` | Root resolution and derived dirs |
| `test_report_stages.py` | Report panel de-duplication + elapsed backfill |
| `test_block_trades.py` | Block-trade point-in-time gating |
| `test_cli_stdout_json.py` | `--output -` stdout contract (MCP depends on it) |
