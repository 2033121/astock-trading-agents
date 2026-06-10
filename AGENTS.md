# AStock Trading Agents

A-share multi-agent quantitative trading decision framework. LangGraph-based pipeline with 15 AI analyst roles producing structured investment ratings through debate.

## Commands

```bash
pip install -e .
astock-trader analyze 600519 --provider deepseek
astock-trader config --show
astock-trader history 600519 --limit 5
astock-trader memory show
pytest tests/
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
│   └── utils/       # states, memory, rating, data tools
├── dataflows/       # Multi-source data (akshare + tushare + eastmoney mx)
├── graph/           # LangGraph orchestration (setup, routing, report gen)
├── llm_clients/     # OpenAI-compatible LLM clients (9 providers)
├── cli/             # Typer CLI
└── default_config.py
```

## Stack

- **Runtime**: Python 3.10+, LangGraph, LangChain
- **Data**: akshare, Tushare Pro REST, EastMoney MX
- **LLM**: OpenAI-compatible (DeepSeek, Qwen, GLM, Ollama, OpenRouter, SiliconFlow, Together, Groq)
- **CLI**: Typer + Rich
- **Models**: Pydantic v2
- **Testing**: pytest

## Pipeline

```
START → 4 Analysts (parallel, ReAct tool loops)
→ Bull/Bear Debate (alternating rounds)
→ Research Manager (synthesizes debate → investment plan)
→ Trader (plan → executable trading strategy)
→ Risk Debate (aggressive → conservative → neutral, multi-round)
→ Portfolio Manager (final decision + rating)
→ Report Generator (deterministic HTML report)
→ END
```

## Style

- snake_case functions/variables, PascalCase classes
- Type hints on all function signatures
- Docstrings in English (Google style); analysis output in Chinese
- Log messages in English
- CLI output rendered by Rich library
- NEVER hardcode API tokens — use environment variables only

## Tests

```bash
pytest tests/ -v
pytest tests/test_schemas.py
pytest tests/test_conditional_logic.py
pytest tests/test_signal_processing.py
pytest tests/test_memory.py
pytest tests/test_dataflows.py
pytest tests/test_agents.py
```

## Boundaries

- Read-only analysis tool — does NOT execute trades
- API keys must come from environment variables, never hardcoded
- Data vendor fallback: 3-level chain per category (e.g., tushare → akshare → mx)
- Report Generator is deterministic (no LLM); elapsed time patched post-graph
- Agent state mutations only through reducer functions
- ReAct agents need explicit empty-message injection (see setup.py)

## Environment

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM API key (most providers) |
| `TUSHARE_TOKEN` | Tushare Pro financial data |
| `MX_APIKEY` | EastMoney MX news data |
| `ASTOCK_REPORT_DIR` | HTML report output directory |
