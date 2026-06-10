# A股智能决策系统

基于 LangGraph 的多Agent辩论式量化交易决策框架，15位AI分析师协作，输出结构化投资评级与可视化分析报告。

> **风险提示**: 本工具仅供研究和辅助决策参考，不构成投资建议。投资有风险，入市需谨慎。

## 核心特性

- **多Agent辩论**: 4位分析师(技术/新闻/舆情/基本面) + 多空辩论 + 三方风控辩论
- **多源数据融合**: Tushare 财务数据 + akshare 行情数据 + 东方财富新闻数据，三级 fallback
- **记忆反思**: 历史决策记忆 + 延迟反思学习
- **可视化报告**: 自动生成可交互 HTML 分析报告，10 阶段流水线过程全透明
- **结构化输出**: Pydantic 模型保证输出格式，支持五级评级(买入/增持/持有/减持/卖出)
- **灵活LLM**: OpenAI兼容接口，支持 DeepSeek/Qwen/GLM/Ollama 等 9 种提供商

## 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        START                                     │
└───────────────────────┬─────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┬───────────────┐
        ▼               ▼               ▼               ▼
 ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
 │  Market      │ │  Social      │ │  News        │ │  Fundamentals│
 │  Analyst     │ │  Analyst     │ │  Analyst     │ │  Analyst     │
 │  (技术面)    │ │  (舆情)      │ │  (新闻)      │ │  (基本面)    │
 └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
        │                │                │                │
        │   [ReAct tool loop: 工具调用 → 数据获取 → 分析]  │
        │                │                │                │
        └────────────────┴────────┬───────┴────────────────┘
                                  ▼
                  ┌───────────────────────────────┐
                  │     Investment Debate          │
                  │   ┌─────────┐   ┌──────────┐  │
                  │   │  Bull   │◄─►│  Bear    │  │
                  │   │Researcher│   │Researcher│  │
                  │   │ (看多)  │   │ (看空)   │  │
                  │   └─────────┘   └──────────┘  │
                  └───────────────┬───────────────┘
                                  ▼
                  ┌───────────────────────────────┐
                  │     Research Manager           │
                  │   综合辩论 → 投资评级方案      │
                  └───────────────┬───────────────┘
                                  ▼
                  ┌───────────────────────────────┐
                  │         Trader                 │
                  │   投资方案 → 交易执行计划      │
                  └───────────────┬───────────────┘
                                  ▼
                  ┌───────────────────────────────┐
                  │     Risk Debate                │
                  │  ┌──────────┐  ┌──────────┐   │
                  │  │Aggressive│─►│Conservat.│   │
                  │  │ (激进)   │  │ (保守)   │   │
                  │  └──────────┘  └────┬─────┘   │
                  │                     ▼          │
                  │              ┌──────────┐      │
                  │              │ Neutral  │      │
                  │              │ (中性)   │      │
                  │              └──────────┘      │
                  └───────────────┬───────────────┘
                                  ▼
                  ┌───────────────────────────────┐
                  │     Portfolio Manager          │
                  │   风控讨论 → 最终投决评级      │
                  └───────────────┬───────────────┘
                                  ▼
                  ┌───────────────────────────────┐
                  │   Report Generator             │
                  │   生成可交互 HTML 分析报告     │
                  └───────────────┬───────────────┘
                                  ▼
                                END
```

**15位AI角色**:

| 角色 | 数量 | 职责 |
|------|------|------|
| 技术分析师 | 1 | 分析价格走势、技术指标、成交量 |
| 新闻舆情分析师 | 1 | 分析个股新闻、政策动态、全球市场联动 |
| 市场情绪分析师 | 1 | 分析大宗交易、资金流向、机构动向 |
| 基本面分析师 | 1 | 分析财报、估值、盈利能力 |
| 看多研究员 | 1 | 从看多角度论证投资理由 |
| 看空研究员 | 1 | 从看空角度提出风险与质疑 |
| 研究经理 | 1 | 综合多空辩论，输出结构化投资评级 |
| 交易员 | 1 | 制定具体交易计划（入场价/止损/仓位） |
| 激进风控分析师 | 1 | 从激进角度评估风险收益比 |
| 保守风控分析师 | 1 | 从保守角度强调风险控制 |
| 中性风控分析师 | 1 | 平衡双方观点给出中立评估 |
| 基金经理 | 1 | 综合风控讨论，做出最终投决 |
| 信号提取器 | 1 | 从决策文本中提取结构化评级 |
| 报告生成器 | 1 | 汇总各阶段产出，生成可交互 HTML 报告 |
| 记忆管理器 | 1 | 存储/检索/反思历史决策 |

## 快速开始

### 环境要求

- Python >= 3.10
- 网络连接（用于调用 LLM API 和获取行情数据）

### 安装

```bash
# 克隆仓库
git clone https://github.com/your-org/astock-trading-agents.git
cd astock-trading-agents

# 开发模式安装
pip install -e .
```

### 配置

#### 1. LLM API 密钥（必须）

```bash
# OpenAI
export OPENAI_API_KEY=sk-your-key-here

# 或 DeepSeek
export OPENAI_API_KEY=sk-your-deepseek-key
export OPENAI_BASE_URL=https://api.deepseek.com
```

支持的 LLM 提供商：

| 提供商 | `--provider` 值 | 默认 Base URL | 所需环境变量 |
|--------|-----------------|---------------|-------------|
| OpenAI | `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| DeepSeek | `deepseek` | `https://api.deepseek.com` | `OPENAI_API_KEY` |
| Qwen/DashScope | `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` |
| GLM/智谱 | `glm` | `https://open.bigmodel.cn/api/paas/v4` | `OPENAI_API_KEY` |
| Ollama (本地) | `ollama` | `http://localhost:11434/v1` | 无需 |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` | `OPENAI_API_KEY` |
| SiliconFlow | `siliconflow` | `https://api.siliconflow.cn/v1` | `OPENAI_API_KEY` |
| Together | `together` | `https://api.together.xyz/v1` | `OPENAI_API_KEY` |
| Groq | `groq` | `https://api.groq.com/openai/v1` | `OPENAI_API_KEY` |

#### 2. 数据源 API（可选但推荐）

| 数据源 | 用途 | 环境变量 | 获取方式 |
|--------|------|---------|---------|
| Tushare Pro | 财务报表、资金流向、股东信息 | `TUSHARE_TOKEN` | [注册获取](https://tushare.pro/register) |
| 东方财富妙想 | 新闻资讯、实时行情 | `MX_APIKEY` | [妙想平台](https://mkapi2.dfcfs.com) |
| akshare | 行情数据、技术指标 | 无需 | 开源库，自动可用 |

系统内置了三级 fallback 机制：当首选数据源不可用时，自动切换到备选源。

#### 3. 报告输出目录（可选）

```bash
# 设置 HTML 报告保存目录
export ASTOCK_REPORT_DIR=/path/to/your/reports
```

未设置时，HTML 报告功能将自动禁用。

### 运行分析

```bash
# 基础用法 — 分析平安银行
astock-trader analyze 000001

# 指定日期和提供商
astock-trader analyze 600519 --date 2025-06-01 --provider deepseek

# 仅选择技术面和基本面分析
astock-trader analyze 300750 --analysts market,fundamentals

# 增加辩论轮数
astock-trader analyze 000001 --debate-rounds 2 --risk-rounds 2

# 指定深度思考模型
astock-trader analyze 600519 --deep-model deepseek-reasoner

# 安静模式（仅输出评级）
astock-trader analyze 000001 --quiet

# 输出到指定文件
astock-trader analyze 000001 --output result.json
```

### 查看历史

```bash
# 查看所有历史
astock-trader history

# 查看特定标的历史
astock-trader history 000001

# 限制条数
astock-trader history 600519 --limit 5
```

### 管理记忆

```bash
# 显示所有记忆条目
astock-trader memory show

# 列出 pending 状态的条目
astock-trader memory resolve

# 清除所有记忆（需确认）
astock-trader memory clear
```

### 配置管理

```bash
# 显示当前配置
astock-trader config --show

# 修改 LLM 提供商
astock-trader config --set llm_provider --value deepseek

# 修改深度思考模型
astock-trader config --set deep_think_llm --value deepseek-reasoner

# 修改快速思考模型
astock-trader config --set quick_think_llm --value deepseek-chat

# 启用检查点（崩溃恢复）
astock-trader config --set checkpoint_enabled --value true

# 重置为默认配置
astock-trader config --reset
```

## CLI 命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `analyze <symbol>` | 运行多Agent分析流水线 | `astock-trader analyze 000001` |
| `history [symbol]` | 查看分析历史记录 | `astock-trader history 600519 --limit 5` |
| `memory <action>` | 管理决策记忆日志 | `astock-trader memory show` |
| `config` | 查看和修改配置 | `astock-trader config --show` |

### `analyze` 选项

| 选项 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--date` | `-d` | 交易日期 YYYY-MM-DD | 今天 |
| `--provider` | `-p` | LLM 提供商 | `openai` |
| `--deep-model` | | 深度思考模型名称 | `deepseek-chat` |
| `--quick-model` | | 快速思考模型名称 | `deepseek-chat` |
| `--base-url` | | 自定义 API Base URL | 按提供商自动选择 |
| `--language` | `-l` | 输出语言 | `Chinese` |
| `--analysts` | `-a` | 分析师组合（逗号分隔） | 全部四个 |
| `--debate-rounds` | | 多空辩论轮数 | `1` |
| `--risk-rounds` | | 风控讨论轮数 | `1` |
| `--checkpoint` | | 启用 SQLite 检查点 | `false` |
| `--output` | `-o` | 输出文件路径 | 自动生成 |
| `--quiet` | `-q` | 安静模式 | `false` |

### `memory` 操作

| 操作 | 说明 |
|------|------|
| `show` | 显示所有记忆条目 |
| `clear` | 清除记忆（需确认） |
| `resolve` | 列出所有 pending 条目 |

## Python API

```python
from astock_trader.graph import TradingAgentsGraph

# 创建分析图
graph = TradingAgentsGraph(
    selected_analysts=["market", "news", "fundamentals"],
    config={
        "llm_provider": "deepseek",
        "deep_think_llm": "deepseek-reasoner",
        "quick_think_llm": "deepseek-chat",
        "max_debate_rounds": 2,
        "max_risk_discuss_rounds": 1,
        "report_output_dir": "./reports",  # HTML 报告保存目录
    },
)

# 运行分析
final_state, rating = graph.propagate("000001", "2025-06-10")

print(f"评级: {rating}")
print(f"最终决策: {final_state.get('final_trade_decision', '')}")
print(f"HTML 报告: {final_state.get('report_path', '')}")
```

### Agent 工厂函数

```python
from astock_trader.agents import (
    create_market_analyst,
    create_bull_researcher,
    create_research_manager,
    create_trader,
    create_aggressive_debator,
)
from astock_trader.llm_clients import create_llm_client

# 创建 LLM
client = create_llm_client(provider="deepseek", model="deepseek-chat")
llm = client.get_llm()

# 创建各角色 Agent
market_node = create_market_analyst(llm)
bull_node = create_bull_researcher(llm)
manager_node = create_research_manager(llm, deep_think_llm=llm)

import functools
trader_node = functools.partial(create_trader(llm), company_name="贵州茅台")
```

### 记忆系统

```python
from astock_trader.agents.utils.memory import TradingMemoryLog

mem = TradingMemoryLog(memory_dir="~/.astock_trader")

# 存储决策
mem.store_decision("000001", "2025-06-10", {
    "rating": "买入",
    "action": "买入",
    "reasoning": "技术面突破",
})

# 获取历史上下文
context = mem.get_past_context("000001")

# 批量更新反思
mem.batch_update_with_outcomes([
    {
        "ticker": "000001",
        "trade_date": "2025-06-10",
        "reflection": {"outcome": "盈利5%", "lesson": "技术分析有效"},
        "new_rating": "增持",
    },
])
```

## QoderWork 集成

本系统可作为 QoderWork 插件使用，在 QoderWork 中直接调用分析能力：

1. 将本项目安装到 QoderWork 环境中
2. 通过 QoderWork 的 Plugin 机制注册 `astock-trader` 命令
3. 在 QoderWork 对话中使用 `/智能分析 000001` 等命令触发分析

也可以通过 QoderWork 的定时任务（Cron）功能设置定期自动分析：

```
每天 15:30 分析自选股列表并生成报告
```

插件包含 4 个 Skill：

| Skill | 说明 |
|-------|------|
| 智能分析 | 运行多Agent分析流水线，输出五级投资评级 |
| 分析历史 | 查看历史分析记录和决策结果 |
| 决策记忆 | 管理决策记忆日志，支持结算和反思 |
| 交易配置 | 查看和修改 LLM 模型、数据源等配置参数 |

## 测试

```bash
# 运行所有测试
pytest tests/

# 详细输出
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_schemas.py
pytest tests/test_conditional_logic.py
pytest tests/test_signal_processing.py
pytest tests/test_memory.py
pytest tests/test_dataflows.py
pytest tests/test_agents.py

# 带覆盖率报告
pytest tests/ --cov=astock_trader --cov-report=term-missing
```

## 项目结构

```
astock-trading-agents/
├── pyproject.toml                  # 项目配置与依赖
├── README.md                       # 本文件
├── LICENSE                         # MIT 许可证
├── skills/                         # QoderWork 插件 Skills
│   ├── 智能分析/                   # 多Agent分析
│   ├── 分析历史/                   # 历史记录查看
│   ├── 决策记忆/                   # 记忆管理
│   └── 交易配置/                   # 配置管理
├── src/
│   └── astock_trader/
│       ├── __init__.py
│       ├── default_config.py       # 默认配置
│       ├── cli/                    # CLI 命令行接口
│       │   ├── __init__.py
│       │   └── main.py             # Typer CLI (analyze/history/memory/config)
│       ├── agents/                 # Agent 定义
│       │   ├── __init__.py         # 顶层导出
│       │   ├── schemas.py          # Pydantic 结构化输出模型
│       │   ├── analysts/           # 分析师 (4位)
│       │   │   ├── market_analyst.py
│       │   │   ├── news_analyst.py
│       │   │   ├── social_media_analyst.py
│       │   │   └── fundamentals_analyst.py
│       │   ├── researchers/        # 研究员 (看多/看空)
│       │   │   ├── bull_researcher.py
│       │   │   └── bear_researcher.py
│       │   ├── managers/           # 经理 (研究/组合)
│       │   │   ├── research_manager.py
│       │   │   └── portfolio_manager.py
│       │   ├── trader/             # 交易员
│       │   │   └── trader.py
│       │   ├── risk_mgmt/          # 风控分析师 (激进/保守/中性)
│       │   │   ├── aggressive_debator.py
│       │   │   ├── conservative_debator.py
│       │   │   └── neutral_debator.py
│       │   └── utils/              # Agent 工具与状态
│       │       ├── agent_states.py
│       │       ├── agent_utils.py
│       │       ├── core_stock_tools.py
│       │       ├── technical_indicators_tools.py
│       │       ├── fundamental_data_tools.py
│       │       ├── news_data_tools.py
│       │       ├── mx_data_tools.py        # 东方财富妙想数据工具
│       │       ├── tushare_data_tools.py   # Tushare 数据工具
│       │       ├── memory.py       # 交易记忆系统
│       │       ├── rating.py       # 评级解析器
│       │       └── structured.py   # 结构化输出工具
│       ├── dataflows/              # 数据层
│       │   ├── __init__.py
│       │   ├── config.py           # 全局配置
│       │   ├── interface.py        # Vendor 路由系统（三级 fallback）
│       │   ├── akshare_data.py     # akshare 数据源（行情/技术指标）
│       │   ├── tushare_data.py     # Tushare 数据源（财务/资金流向）
│       │   ├── mx_data.py          # 东方财富妙想数据源（新闻/实时）
│       │   └── eastmoney_news.py   # 东方财富新闻源
│       ├── graph/                  # LangGraph 编排层
│       │   ├── __init__.py
│       │   ├── setup.py            # 图构建与编译
│       │   ├── trading_graph.py    # 主编排器
│       │   ├── conditional_logic.py # 条件路由
│       │   ├── propagation.py      # 状态传播
│       │   ├── reflection.py       # 反思机制
│       │   ├── signal_processing.py # 信号提取
│       │   ├── report_generator.py # HTML 报告生成器
│       │   └── checkpointer.py     # SQLite 检查点
│       └── llm_clients/            # LLM 客户端
│           ├── __init__.py
│           ├── base_client.py      # 基类
│           ├── openai_client.py    # OpenAI 兼容客户端
│           └── factory.py          # 客户端工厂
└── tests/                          # 测试
    ├── conftest.py
    ├── test_schemas.py             # Pydantic 模型测试
    ├── test_conditional_logic.py   # 条件路由测试
    ├── test_signal_processing.py   # 信号提取测试
    ├── test_memory.py              # 记忆系统测试
    ├── test_dataflows.py           # 数据层路由测试
    └── test_agents.py              # Agent 工厂测试
```

## 评级体系

系统输出五级投资评级：

| 评级 | 含义 | 建议操作 |
|------|------|----------|
| **买入** | 强烈看多，多维度共振 | 积极建仓 |
| **增持** | 偏多，有上行空间 | 逢低加仓 |
| **持有** | 中性，方向不明确 | 观望等待 |
| **减持** | 偏空，风险偏高 | 逐步减仓 |
| **卖出** | 强烈看空，破位信号 | 止损离场 |

## 致谢

本项目灵感来自 [TradingAgents](https://github.com/TauricResearch/TradingAgents) 框架，针对A股市场进行了全面适配和增强。

## License

MIT
