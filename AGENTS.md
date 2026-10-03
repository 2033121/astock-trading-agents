# AStock Trading Agents

A-share multi-agent quantitative trading decision framework. LangGraph-based pipeline with 15 AI agent roles producing structured investment ratings through debate.

Usage from agent hosts (Claude Code / Codex / Trae / Qoder / any MCP host): see `docs/Agent接入指南.md`.

## Commands

```bash
pip install -e .
astock-trader analyze 600519 --provider deepseek            # 2-8 min, real tokens
astock-trader analyze 000155 --quiet --output -             # JSON on stdout
astock-trader watch 600519 --once                           # one monitor tick
astock-trader config --show
astock-trader history 600519 --limit 5
astock-trader memory show
pytest tests/                                               # 799 tests
python -m ruff check src/ tests/ mcp_server.py
```

## Structure

```
src/astock_trader/
├── agents/          # 15 AI agent definitions
│   ├── analysts/    # 4 parallel analysts (market/news/social/fundamentals)
│   ├── researchers/ # bull/bear debate pair
│   ├── managers/    # research manager + portfolio manager
│   ├── trader/      # trading plan generator
│   ├── risk_mgmt/   # 3-way risk debate (aggressive/conservative/neutral)
│   └── utils/       # states, memory, rating, data tool wrappers
├── dataflows/       # Multi-source data (akshare + tushare + eastmoney mx + gdelt + realtime)
├── graph/           # LangGraph orchestration (setup, routing, report gen)
├── monitor/         # Watch layer: rules DSL, polling engine, event store, notifier (no LLM)
├── external_calibration/  # Third-party scoreboard ledger (isolated from internal memory)
├── llm_clients/     # OpenAI-compatible LLM clients (9 providers)
├── cli/             # Typer CLI (analyze/watch/history/memory/config)
├── paths.py         # Single source of truth for the project root
└── default_config.py

mcp_server.py        # Zero-dependency MCP stdio server (5 tools)
skills/              # 7 agent-invocable workflows
```

## Stack

- **Runtime**: Python 3.10+, LangGraph, LangChain
- **Data**: akshare, Tushare Pro REST, EastMoney MX, GDELT
- **LLM**: OpenAI-compatible (DeepSeek, Qwen, GLM, Ollama, OpenRouter, SiliconFlow, Together, Groq, MiMo)
- **CLI**: Typer + Rich
- **Models**: Pydantic v2
- **Testing**: pytest

## Pipeline

```
START → 4 Analysts [Light] (parallel, ReAct tool loops)
→ Bull/Bear Debate [Deep] (alternating rounds)
→ Research Manager [Standard] (synthesizes debate → investment plan)
→ Trader [Standard] (plan → executable trading strategy)
→ Risk Debate [Standard] (aggressive → conservative → neutral, multi-round)
→ Portfolio Manager [Deep] (final decision + rating)
→ Report Generator [Light] (deterministic HTML report)
→ END
```

## Model Allocation

| Tier | Config Key | Agents | Rationale |
|------|-----------|--------|-----------|
| **Deep** | `deep_think_llm` | Portfolio Manager | Final decision |
| **Heavy** | `heavy_think_llm` | Bull/Bear Researchers | Argumentation |
| **Standard** | `standard_think_llm` | Research Manager, Trader, 3 Risk Analysts | Balanced |
| **Light** | `quick_think_llm` | 4 Analysts, SignalProcessor, Report Generator | Fast collection |

## Style

- snake_case functions/variables, PascalCase classes
- Type hints on all function signatures
- Docstrings in English (Google style); analysis output in Chinese
- Log messages in English
- CLI output rendered by Rich library
- NEVER hardcode or commit API tokens — environment variables or `user_config.json` only
- Comments explain **why**, not what

## Tests

```bash
pytest tests/ -v
pytest tests/test_schemas.py
pytest tests/test_conditional_logic.py
pytest tests/test_signal_processing.py
pytest tests/test_memory.py
pytest tests/test_dataflows.py
pytest tests/test_agents.py

# Regression guards for silent-failure bug classes — run these when touching
# the data layer, tool wrappers, or graph state:
pytest tests/test_tool_signatures.py          # wrapper vs vendor parameter names
pytest tests/test_debate_state_merge.py       # debate history not overwritten
pytest tests/test_dataflows_config_wiring.py  # config reaches the data layer
pytest tests/test_ohlcv_fallback.py           # three-source fallback + units
pytest tests/test_rating_action.py            # negation-aware rating parsing
pytest tests/test_cli_stdout_json.py          # --output - stdout contract
```

## Boundaries

- Read-only analysis tool — does NOT execute trades
- API keys/tokens come from env vars or `user_config.json` (repo-external), never hardcoded or committed
- **Nested state reducers do not work in this LangGraph version.** `investment_debate_state` /
  `risk_debate_state` are replaced wholesale on every write, so debate nodes MUST go through
  `setup._merge_debate()`. Symptom of getting this wrong is silent: the report still renders, one
  side's arguments just vanish.
- Data vendor fallback is **per method** (`interface.VENDOR_METHODS`), not per category. Fallback
  triggers on an exception *or* an `"[ERROR] ..."` soft-failure string.
- `TradingAgentsGraph.__init__` pushes config into the `dataflows` singleton; without it
  `get_config()` is `{}` and credentials silently never reach the vendors.
- Credential precedence is **config-first, then env var** (a stale env token otherwise shadows a
  freshly configured one).
- Report Generator is deterministic (no LLM); elapsed time is patched post-graph into both the
  JSON field and the summary prose.
- ReAct agents need explicit empty-message injection (see `setup.py`); msg-clear warns when a
  message lacks an `id`, because an uncleared message leaks the previous analyst's system prompt.
- Never hardcode `~/.astock_trader` — use `astock_trader.paths.project_dir()`.
- Tool wrappers must mirror their vendor's parameter names exactly (`trade_date` may be injected
  via `InjectedState` and converted to `curr_date`, but everything else must match).

## Environment

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `MIMO_API_KEY` / `LLM_API_KEY` | LLM API key (one of) |
| `TUSHARE_TOKEN` | Tushare Pro financial data |
| `MX_APIKEY` | EastMoney MX news data |
| `ASTOCK_HOME` | Project root (all output dirs derive from it) |
| `ASTOCK_REPORT_DIR` | HTML report dir |
| `ASTOCK_SNAPSHOT_LOG_PATH` | Snapshot ledger path (MCP) |
| `ASTOCK_MCP_CLI_TIMEOUT` | MCP subprocess timeout, default 1200s |

## Skills (agent-invocable workflows)

Directory `skills/` — each subfolder has a SKILL.md with frontmatter
(name / description / trigger words). Multi-host installer:

```bash
./integrations/install.sh [dsh|claude|codex|zcode ...] [--dry-run] [--force]
```

| Skill | Codex prompt slug | Trigger words |
|-------|-------------------|---------------|
| 智能分析 | astock-analysis | 分析、股票分析、analyze |
| 分析历史 | astock-history | 历史、分析历史 |
| 决策记忆 | astock-memory | 记忆、决策记忆 |
| 交易配置 | astock-config | 配置、交易配置 |
| 快照跟踪对比 | astock-snapshot-tracking | 快照对比、评级变化 |
| 龙虎榜解读 | astock-lhb-interpretation | 龙虎榜、席位 |
| 行业对比解读 | astock-industry-comparison | 行业对比、估值分位 |

Hosts: DSH & Claude Code & zCode load `skills/<dir>` via symlink;
Codex CLI consumes `~/.codex/prompts/astock-<slug>.md`; any AGENTS.md-based
host can follow the trigger words and open the referenced SKILL.md directly.
