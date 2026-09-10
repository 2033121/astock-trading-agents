[中文](README.md) | English

# AStock Trading Agents

A debate-style, multi-agent trading decision framework for China A-shares,
built on LangGraph. 15 AI roles collaborate through analysts, bull/bear
debates, three-way risk debates and a portfolio manager to produce a
structured rating plus an interactive HTML report. A condensed English
guide is kept here; the [Chinese README](README.md) remains the
authoritative full reference.

> **Disclaimer**: For research and decision-support only. Not investment advice.

## Why this differs from other agent frameworks

- **Debate architecture** — 4 analysts produce independent evidence; bull/bear
  researchers argue for at least one full round plus a final rebuttal before a
  research manager adjudicates; three risk personas (aggressive / conservative
  / neutral) challenge the trade plan; the portfolio manager makes the final call.
- **Reflection loop** — every decision is snapshotted, marked against realised
  5/10/20-day returns via akshare, and fed back as decayed, quality-gated
  prompt context (`backtest_feedback.json`).
- **A-share-native** — T+1, limit-up/down board rules, red-up/green-down
  conventions, CJK-tolerant signal extraction, akshare/tushare data stack.
- **Token-aware pipeline** — configurable four-tier model routing, shared
  system-prefix prompt caching, deterministic context digests (researchers)
  and a decision matrix (portfolio manager), plus an optional node-level
  semantic response cache. Overall pipeline usage reduction is material
  (~25% baseline, more with caches).

## Architecture (15 roles)

| Role | Count | Purpose |
|------|-------|---------|
| Market / News / Sentiment / Fundamentals analyst | 4 | Evidence gathering with ReAct tools |
| Bull / Bear researcher | 2 | Adversarial debate with final rebuttal |
| Research manager | 1 | Adjudicate debate → investment rating |
| Trader | 1 | Entry / stop-loss / position sizing plan |
| Aggressive / Conservative / Neutral risk | 3 | Three-way risk debate |
| Portfolio manager | 1 | Final decision (structured Pydantic output) |
| Signal extractor / Report generator / Memory manager | 3 | Deterministic rating extraction, HTML report, reflection memory |

## Ratings (CN ↔ EN glossary)

| 中文 | English |
|------|---------|
| 买入 | Buy |
| 增持 | Overweight / Accumulate |
| 持有 | Hold |
| 减持 | Underweight / Reduce |
| 卖出 | Sell |

## Quick start

```bash
pip install -e ".[dev]"
export DEEPSEEK_API_KEY=...          # any OpenAI-compatible provider
astock-trader analyze 600519 --provider deepseek --date 2025-06-01
```

Common options: `--date`, `--provider`, `--analysts market,fundamentals`,
`--debate-rounds`, `--deep-model`, `--quiet`, `--output report.json`,
`--language Chinese|English`.

## MCP server

A zero-dependency MCP stdio server (`mcp_server.py`) exposes the framework to
any MCP host (e.g. Claude Desktop):

```json
{
  "mcpServers": {
    "astock-trading-agents": {
      "command": "python",
      "args": ["D:/Qoder/astock-trading-agents/mcp_server.py"]
    }
  }
}
```

Tools: `analyze_stock` (full pipeline), `list_snapshots`, `get_snapshot`,
`read_recent_memories`, `review_backtest` (rating-vs-realised backtest).

## Token savings (docs/Token控制改进方案.md)

| Strategy | Status | Mechanism |
|----------|--------|-----------|
| Tiered model routing | ✅ existing | heavy→debaters, standard→managers/risk, quick→analysts |
| Shared system prompt prefix (2B) | ✅ `prompt_prefix.py` | provider KV-cache discount (DeepSeek ~90%+) |
| Structured context passing (2A) | ✅ | deterministic prose digest for researchers + PM decision matrix (0 extra tokens) |
| Semantic response cache (3) | ✅ optional | TTL/LRU cache at node level, off by default |
| Rule-engine signal extraction | ✅ existing | final rating parsed with 0 tokens |

## Tests & CI

- `pytest tests/ -q` — 241 tests (agents routing, context slimming, semantic
  cache, PM matrix, MCP server, signal processing, memory, dataflows).
- GitHub Actions: ruff lint + pytest matrix (3.10/3.11/3.12).

## License

MIT — see [LICENSE](LICENSE).
