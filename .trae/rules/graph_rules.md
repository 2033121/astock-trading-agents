---
description: "graph 目录开发规则 — LangGraph 编排层"
paths: ["src/astock_trader/graph/**/*.py"]
---

# LangGraph 编排层规则

## 图构建 (setup.py)

- `GraphSetup` 类负责构建 `StateGraph`
- 节点通过工厂方法创建（闭包捕获 config）
- 边路由：条件边用于辩论循环，普通边用于线性流转
- 拓扑：START → Analysts → Debate → Research Manager → Trader → Risk Debate → Portfolio Manager → Report Generator → END

## 主编排器 (trading_graph.py)

- `TradingAgentsGraph` 是对外入口
- `_create_llms()` 按优先级查找 API Key：OPENAI > DEEPSEEK > DASHSCOPE > LLM_API_KEY
- 当模型名含 "deepseek" 且未指定 `backend_url` 时，自动切换到 `https://api.deepseek.com/v1`
- `_run_graph()` 记录 `t0`/`elapsed`，完成后通过 `_patch_report_elapsed()` 回填 HTML

## Report Generator (report_generator.py)

- 纯 Python 函数，不调用 LLM
- 从 AgentState 提取 9 个阶段产出 + 自动生成的"报告总结"
- HTML 模板使用 marked.js CDN 渲染 Markdown
- 文件保存到 `{report_output_dir}/{ticker}_{date}_report.html`
- `report_output_dir` 为空时跳过生成，返回空路径

## 信号提取 (signal_processing.py)

- `SignalProcessor.process_signal()` 从 Portfolio Manager 决策文本中提取评级
- 支持五级：买入/增持/持有/减持/卖出
- 结果存入 `state["_rating"]`

## 状态传播 (propagation.py)

- `propagate()` 函数创建初始 AgentState
- 所有字段初始化为空字符串/空列表
- `company_of_interest` 和 `trade_date` 从参数注入
