# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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

[0.1.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.1.0
