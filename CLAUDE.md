# AStock Trading Agents — Project Instructions

A-share multi-agent quantitative trading decision framework based on LangGraph. 15 AI analyst roles collaborate through structured debate to produce investment ratings.

## Quick Commands

```bash
# Install
pip install -e .

# Run analysis
astock-trader analyze 600519 --date 2026-06-10 --provider deepseek

# Run tests
pytest tests/
pytest tests/test_schemas.py -v

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
  - `utils/` — agent_states.py (AgentState), memory.py, rating.py, data tools
- `src/astock_trader/dataflows/` — Multi-source data layer with 3-level vendor fallback
  - `interface.py` — Vendor routing (akshare → tushare → mx fallback chain)
  - `akshare_data.py` — Market data & technical indicators
  - `tushare_data.py` — Financial statements, capital flow, shareholder info
  - `mx_data.py` — EastMoney MX news & real-time data
- `src/astock_trader/graph/` — LangGraph orchestration
  - `setup.py` — Graph construction, node factory, edge routing
  - `trading_graph.py` — Main orchestrator, API key resolution, elapsed time tracking
  - `report_generator.py` — Deterministic HTML report generator (no LLM call)
  - `signal_processing.py` — Rating extraction from decision text
  - `propagation.py` — Initial state factory
- `src/astock_trader/llm_clients/` — LLM client abstraction (9 providers via OpenAI-compatible API)
- `src/astock_trader/cli/` — Typer-based CLI (analyze, history, memory, config)
- `skills/` — QoderWork plugin skills (智能分析, 分析历史, 决策记忆, 交易配置)
- `tests/` — pytest test suite (151 tests)

## Pipeline Topology

```
START → 4 Analysts (parallel) → Bull/Bear Debate → Research Manager
→ Trader → Risk Debate (aggressive→conservative→neutral)
→ Portfolio Manager → Report Generator → END
```

## Key Patterns

- **Agent factory functions** return LangChain Runnable objects; node factories in `setup.py` create closures capturing config
- **AgentState** uses `MessagesState` with `add_messages` reducer; debate sub-states use `_append_str_list` reducer
- **ReAct empty message fix**: `setup.py._create_llm_agent()` injects SystemMessage + HumanMessage when messages list is empty
- **Report Generator**: deterministic node (no LLM), runs inside graph with `elapsed=0`; `trading_graph.py` patches HTML with actual elapsed time after graph completion
- **Data vendor fallback**: 3-level priority chain per data category (core_stock, technical_indicators, fundamental_data, news_data)
- **Rating system**: 5-level (买入/增持/持有/减持/卖出), extracted from portfolio manager's decision text

## Coding Conventions

- Python 3.10+, use type hints everywhere
- Docstrings in English (Google style); analysis output in Chinese
- snake_case for functions/variables, PascalCase for classes
- CLI uses Typer with Rich for terminal rendering
- All API keys via environment variables, NEVER hardcode tokens
- State mutations through reducer functions only
- Log messages in English via `logging` module

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | Yes (most providers) | LLM API authentication |
| `DEEPSEEK_API_KEY` | For DeepSeek direct | DeepSeek API key |
| `DASHSCOPE_API_KEY` | For Qwen | Alibaba DashScope key |
| `TUSHARE_TOKEN` | Recommended | Tushare Pro financial data ([register](https://tushare.pro/register)) |
| `MX_APIKEY` | Optional | EastMoney MX news data |
| `ASTOCK_REPORT_DIR` | Optional | HTML report output directory |

## Data Sources

- **Tushare Pro**: Financial statements, capital flow, shareholder data (env: `TUSHARE_TOKEN`)
- **akshare**: Market data, technical indicators (open source, no key needed)
- **EastMoney MX**: News, real-time quotes (env: `MX_APIKEY`)

## Testing

```bash
pytest tests/                                          # All tests
pytest tests/ -v                                       # Verbose
pytest tests/ --cov=astock_trader --cov-report=term-missing  # Coverage
```
