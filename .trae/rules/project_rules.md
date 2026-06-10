---
description: "AStock Trading Agents 全局开发规则 — A股多智能体量化决策框架"
---

# 项目概述

AStock Trading Agents 是一个基于 LangGraph 的 A 股多智能体量化交易决策框架。15 位 AI 分析师通过结构化辩论产出投资评级（买入/增持/持有/减持/卖出）。

## 核心架构

流水线拓扑：`START → 4 Analysts (并行) → Bull/Bear Debate → Research Manager → Trader → Risk Debate (三方) → Portfolio Manager → Report Generator → END`

### 关键模块

- `src/astock_trader/agents/` — 智能体定义（分析师、研究员、经理、交易员、风控）
- `src/astock_trader/dataflows/` — 多源数据层（akshare + Tushare + 东方财富 MX），三级 fallback
- `src/astock_trader/graph/` — LangGraph 编排层（图构建、路由、报告生成、信号提取）
- `src/astock_trader/llm_clients/` — OpenAI 兼容 LLM 客户端（9 种提供商）
- `src/astock_trader/cli/` — Typer CLI（analyze, history, memory, config）

## 开发规范

### 代码风格

- Python 3.10+，所有函数签名加 type hints
- 函数/变量用 snake_case，类用 PascalCase
- 文档字符串用英文（Google 风格），分析产出用中文
- 日志消息用英文，通过 `logging` 模块输出
- CLI 输出使用 Rich 库渲染

### 安全规则

- **永远不要硬编码 API Token** — 所有密钥通过环境变量获取
- `TUSHARE_TOKEN`、`MX_APIKEY`、`OPENAI_API_KEY` 等均从 `os.environ` 读取
- `default_config.py` 中不应出现硬编码的本地路径

### 架构约束

- 智能体状态变更只能通过 reducer 函数
- AgentState 使用 `MessagesState` + `add_messages` reducer
- 辩论子状态使用 `_append_str_list` reducer 累积历史
- ReAct Agent 需要空消息注入处理（见 `setup.py._create_llm_agent()`）
- Report Generator 是确定性节点（不调 LLM），运行在图内部时 `elapsed=0`，图完成后由 `trading_graph.py` 回填实际耗时
- 数据供应商 fallback 是三级优先级链（每个数据类别独立配置）

### 测试

```bash
pip install -e .
pytest tests/ -v
pytest tests/ --cov=astock_trader --cov-report=term-missing
```

### 环境变量

| 变量 | 用途 |
|------|------|
| `OPENAI_API_KEY` | LLM API 认证（大多数提供商） |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `DASHSCOPE_API_KEY` | 阿里 DashScope 密钥 |
| `TUSHARE_TOKEN` | Tushare Pro 财务数据 |
| `MX_APIKEY` | 东方财富妙想新闻数据 |
| `ASTOCK_REPORT_DIR` | HTML 报告输出目录 |
