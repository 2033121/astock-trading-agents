---
description: "agents 目录开发规则 — 智能体定义与状态管理"
paths: ["src/astock_trader/agents/**/*.py"]
---

# 智能体模块规则

## 智能体工厂模式

- 每个智能体文件导出一个 `create_xxx(llm, ...)` 工厂函数
- 工厂函数返回 LangChain `Runnable` 对象
- `setup.py` 中的节点工厂函数创建闭包，捕获 config 值（如 `max_debate_rounds`）

## AgentState

- 定义在 `utils/agent_states.py`
- 使用 `MessagesState` + `add_messages` reducer
- `report_path` 字段由 Report Generator 节点写入
- 辩论子状态（`InvestDebateState`, `RiskDebateState`）有独立的 reducer

## 新增智能体的步骤

1. 在对应子目录创建 `.py` 文件
2. 导出 `create_xxx(llm)` 工厂函数
3. 在 `__init__.py` 中导出
4. 在 `graph/setup.py` 中注册为节点
5. 添加对应的 state 字段到 `agent_states.py`（如需）
6. 在 `tests/test_agents.py` 中添加工厂函数测试

## 数据工具

- `core_stock_tools.py` — 行情数据（akshare）
- `technical_indicators_tools.py` — 技术指标（akshare）
- `fundamental_data_tools.py` — 财务数据（Tushare 首选）
- `news_data_tools.py` — 新闻数据（MX 首选）
- `mx_data_tools.py` / `tushare_data_tools.py` — 直接数据源工具
