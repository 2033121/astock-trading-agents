# Agent 接入指南

把本框架接进 AI 编程助手 / Agent 宿主的方式有**三条**，彼此独立、可以叠加：

| 姿势 | 面向 | 能力 | 需要装什么 |
|------|------|------|-----------|
| **CLI 直用** | 任何能执行 shell 的 agent | 全功能：分析、历史、记忆、配置、盯盘 | `pip install -e .` |
| **Skills** | Claude Code / Codex / zCode / DSH / QoderWork / Trae | 把上述命令包成可触发的「技能」，带触发词与输出规范 | `./integrations/install.sh` |
| **MCP** | 任何 MCP 宿主（Claude Desktop / Cline / Continue / Zed…） | 5 个结构化工具，含一次完整分析 | 仅标准库，无需装包 |

选哪个：**只想让 agent 会分析** → CLI + Skills；**想让 agent 把分析结果当结构化数据用** → MCP；**两者都要** → 都装，它们共享同一份数据闭环（见 [附录 A](#附录-a数据闭环与文件落点)）。

---

## 0. 通用准备

### 0.1 安装

```bash
git clone https://github.com/2033121/astock-trading-agents.git
cd astock-trading-agents
pip install -e .          # 开发模式；只装 CLI 用 pip install .
astock-trader --help      # 验证
```

### 0.2 LLM 凭证

`backend_url` + 一个 API key 即可跑通（任何 OpenAI 兼容端点）。

**优先级：`user_config.json` → 环境变量。** 配置优先是刻意的：环境里常留着一个旧的、
已失效的 key，它会把新值静默顶掉（本项目就此踩过一次，见
仓库根的 `CHANGELOG.md`）。

```bash
# 方式一：写进用户级配置（推荐，一次配好，仓库之外）
astock-trader config --set api_key      --value sk-your-key
astock-trader config --set backend_url  --value https://api.deepseek.com
astock-trader config --set llm_provider --value deepseek

# 方式二：环境变量（按 provider 取对应变量）
export OPENAI_API_KEY=sk-...        # provider=openai 时
export DEEPSEEK_API_KEY=sk-...      # provider=deepseek 时
```

支持的 provider：`openai` / `deepseek` / `qwen` / `glm` / `ollama` / `openrouter` /
`siliconflow` / `together` / `groq` / `mimo`。详见仓库根的 `README.md`「配置」一节。

### 0.3 数据源凭证（可选但强烈建议）

| 变量 / 配置键 | 作用 | 不配的后果 |
|---|---|---|
| `TUSHARE_TOKEN` 或 `config --set tushare_token` | 财务、资金流、股东、融资融券 | 直接丢掉 PE/PB、资金流向、股东增减持、财务指标 |
| `MX_APIKEY` | 东方财富妙想新闻 | 新闻走更弱的兜底源 |

行情日线（OHLCV）与技术指标**免 Key**，内置东方财富 → 新浪 → 腾讯三源 fallback，
不需要配置。

### 0.4 目录落点

所有运行时产物都落在**一个项目根**下：

| 平台 | 默认根 |
|---|---|
| Windows（有 D 盘） | `D:\astock_trader` |
| 其他 | `~/.astock_trader` |

用 `ASTOCK_HOME` 整体搬走。`user_config.json`、`monitor.json`、报告、记忆、台账
全部在这个根下，**都在仓库之外** —— 所以凭证永远不会被提交。

> 写脚本时不要硬编码 `~/.astock_trader`，用
> `python -c "from astock_trader.paths import project_dir; print(project_dir())"`。

### 0.5 自检

```bash
astock-trader config --show          # 看配置（含凭证是否存在）
astock-trader history --limit 3      # 看记忆是否可读
astock-trader analyze 000001 --analysts market --quiet   # 最小管线
```

---

## 1. 命令行直用（任何 agent）

五个顶层命令：

```bash
astock-trader analyze 000155              # 15 角色完整分析 → 五级评级
astock-trader watch 600519 000001         # 常驻盯盘，命中规则推送通知
astock-trader history 000155 --limit 5    # 历史分析记录
astock-trader memory show                 # 决策记忆（反思闭环）
astock-trader config --show               # 配置
```

### 给程序消费：`--quiet --output -`

```bash
astock-trader analyze 000155 --quiet --output -
```

- `--output -` → 结果 **JSON 写到 stdout**（UTF-8 字节，不随本机区域设置变化）
- `--quiet` → 抑制所有 Rich 装饰输出，stdout 上只有那一份 JSON
- 不带 `-` 时 `--quiet` 输出一行 TSV：`代码\t日期\t评级`

复杂命令行的完整选项见 `README.md`「CLI 命令」一节，或 `astock-trader <cmd> --help`。

> ⚠️ 一次 `analyze` 要跑 15 个 LLM 角色，**耗时约 2–8 分钟**并消耗真实 token。
> 让 agent 自动调用前先想清楚触发条件。

---

## 2. Claude Code

**三层能力都支持。**

### 2.1 项目指令（自动）

仓库根的 `CLAUDE.md` 在会话启动时自动加载，无需配置。它包含项目结构、常用命令、
架构约束、环境变量清单。

### 2.2 Skills

```bash
./integrations/install.sh claude          # 软链到 ~/.claude/skills/astock-*
./integrations/install.sh claude --dry-run # 先看看会做什么
```

安装后重启 Claude Code，用 `/` 可以看到技能。7 个技能：

| 技能 | 触发词 | 做什么 |
|------|--------|--------|
| 智能分析 | 分析、股票分析 | 跑完整流水线，解读五级评级 |
| 分析历史 | 历史、分析历史 | Rich 表格复盘历史记录 |
| 决策记忆 | 记忆、决策记忆 | show / resolve / clear 记忆条目 |
| 交易配置 | 配置 | 改 LLM / 数据源 / 辩论轮数 |
| 快照跟踪对比 | 快照对比、评级变化 | 多期快照对比与方向一致性 |
| 龙虎榜解读 | 龙虎榜、席位、游资 | 席位结构 → 资金信号摘要 |
| 行业对比解读 | 行业对比、估值分位 | 相对估值横截面 |

> 前 4 个技能的 frontmatter 用中文 `name:`（如 `name: 智能分析`），后 3 个用
> ascii slug。若某个技能在 `/` 列表里不出现或无法用斜杠调用，直接说触发词让
> agent 读取对应的 `skills/<目录>/SKILL.md` 即可 —— 技能文件本身就是给人读的
> 工作流说明。

### 2.3 MCP

```bash
claude mcp add astock-trading-agents -- python /绝对路径/mcp_server.py
```

或手写配置（见 [第 7 节](#7-任意-mcp-宿主)）。

### 2.4 典型对话

```
你：分析一下川能动力
   → 智能分析技能触发 → astock-trader analyze 000155
   → 返回评级、决策正文、报告路径

你：这只票之前分析过吗？评级变了吗
   → 快照跟踪对比技能 → 读快照台账 → 呈现评级/价格演变
```

---

## 3. OpenAI Codex CLI

### 3.1 项目指令（自动）

仓库根的 `AGENTS.md` 在 Codex 启动时自动加载 —— Commands / Structure / Stack /
Pipeline / Model Allocation / Style / Tests / Boundaries 九大板块。

### 3.2 Skills → slash commands

Codex CLI 不读 `skills/` 目录，安装器会把每个技能的 `SKILL.md` **复制**成一条
slash 命令：

```bash
./integrations/install.sh codex      # → ~/.codex/prompts/astock-<slug>.md
```

| 技能 | Codex 命令 |
|------|-----------|
| 智能分析 | `/astock-analysis` |
| 分析历史 | `/astock-history` |
| 决策记忆 | `/astock-memory` |
| 交易配置 | `/astock-config` |
| 快照跟踪对比 | `/astock-snapshot-tracking` |
| 龙虎榜解读 | `/astock-lhb-interpretation` |
| 行业对比解读 | `/astock-industry-comparison` |

### 3.3 MCP

Codex CLI 支持 MCP，配置方式与其它宿主一致。

---

## 4. 其他 AGENTS.md 宿主

**凡是认 `AGENTS.md` 约定的宿主**（zCode、Cursor、Windsurf、Cline、Amp 等），
把本仓库加进工作区即可 —— `AGENTS.md` 会被自动读取。

```bash
./integrations/install.sh zcode      # zCode：软链技能到 ~/.zcode/skills/
```

对于**只读 `AGENTS.md`、不加载技能目录**的宿主，让 agent 按触发词直接打开
对应的 `skills/<目录>/SKILL.md`：那个文件就是一份自包含的工作流说明，不依赖
任何宿主特性。

> 本仓库目前**没有**提供 `.cursor/rules/*.mdc`、`.windsurfrules`、
> `.github/copilot-instructions.md` —— 这三种宿主请依赖各自的 `AGENTS.md` 读取，
> 或手动把 `AGENTS.md` 的内容复制到对应文件。

---

## 5. Trae IDE

`.trae/rules/` 下的规则文件会被 Trae 自动注入上下文，其中两个是**按路径挂载**的：

| 文件 | 作用域 | 内容 |
|------|--------|------|
| `project_rules.md` | 全局 | 项目概览、架构、开发规范、安全规则 |
| `agents_rules.md` | `src/astock_trader/agents/**/*.py` | 智能体工厂模式、AgentState、新增智能体步骤 |
| `graph_rules.md` | `src/astock_trader/graph/**/*.py` | LangGraph 编排层规则 |

打开对应目录的文件时规则才生效。无需额外配置。

---

## 6. Qoder / QoderWork

仓库自带 Qoder 原生插件描述 `/.qoder-plugin/plugin.json`，声明了技能列表。在
QoderWork 中还可以用定时任务把分析挂成周期作业（例如「每天 15:30 分析自选股并
推送」）。Skills 的加载方式与 Claude Code 相同（软链技能目录）。

---

## 7. 任意 MCP 宿主

### 7.1 五个工具

| 工具 | 必填参数 | 说明 |
|------|---------|------|
| `analyze_stock` | `symbol` | 跑完整 15 角色管线，返回评级 / 决策正文 / 报告路径 / 耗时。**耗时 2–8 分钟，且真的消耗 LLM token** |
| `list_snapshots` | — | 最近的分析快照，含 T+1/T+5/T+10/T+20 追踪收益 |
| `get_snapshot` | `stock_code` | 单只股票的最新快照 + 评级时间线 + 累计价格变化 |
| `read_recent_memories` | — | 最近的决策记忆条目（反思闭环结论） |
| `review_backtest` | — | 回测复盘：评级与实际行情对照、准确率统计 |

后 4 个是**纯文件读取**（毫秒级、零 token），可以放心让 agent 频繁调用。
只有 `analyze_stock` 是重的。

### 7.2 配置

```json
{
  "mcpServers": {
    "astock-trading-agents": {
      "command": "python",
      "args": ["/绝对路径/astock-trading-agents/mcp_server.py"],
      "env": {
        "ASTOCK_HOME": "/可选/自定义项目根"
      }
    }
  }
}
```

Claude Desktop 用 `claude_desktop_config.json`；Claude Code 用
`claude mcp add astock-trading-agents -- python /绝对路径/mcp_server.py`；
Cline / Continue / Zed 等在各自的 MCP 设置里填同一段。

### 7.3 环境变量

| 变量 | 默认 | 作用 |
|------|------|------|
| `ASTOCK_HOME` | `D:\astock_trader` / `~/.astock_trader` | 项目根，决定记忆与报告位置 |
| `ASTOCK_MCP_CLI_TIMEOUT` | `1200`（秒） | `analyze_stock` / `review_backtest` 的子进程超时 |
| `ASTOCK_SNAPSHOT_LOG_PATH` | 见 `scripts/save_snapshot.py` | 快照台账路径 |
| `ASTOCK_MEMORY_LOG_PATH` | `<项目根>/memory/trading_memory.md` | 决策记忆 markdown |

### 7.4 依赖

`mcp_server.py` **只用标准库**，不需要 `pip install` 本项目就能启动。但
`analyze_stock` / `review_backtest` 内部会起子进程调 CLI / 脚本，所以
**那两条路径要求项目已安装**。

---

## 8. 进度面板

长分析跑起来后，可以让 agent 同时开一个自刷新的侧边栏：

```bash
astock-trader analyze 600519                      # 过程中写 <symbol>_<date>_progress.jsonl
python3 scripts/agent_panel.py <results_dir>/600519_20260911_progress.jsonl
```

生成的 `agent_panel.html` 每 2 秒自刷新，按阶段显示各角色的运行中/完成/失败、
耗时与最终评级。DSH 用 `sidebar_open` 打开；其他宿主直接在浏览器打开。

---

## 附录 A：数据闭环与文件落点

三条接入面**共享同一份数据**，所以 CLI 跑出来的分析，MCP 那边立刻能查到：

```
astock-trader analyze 000155
   ├─→ <项目根>/logs/000155_2026-10-03_result.json    结果 JSON
   ├─→ <项目根>/reports/000155_2026-10-03_report.html  HTML 报告
   ├─→ <项目根>/trading_memory.log                     决策记忆（追加）
   └─→ <项目根>/vector_memory/                         向量索引
            ↓
   scripts/save_snapshot.py          → 快照台账（ASTOCK_SNAPSHOT_LOG_PATH）
            ↓
   scripts/review_backtest.py        → 回填 T+1/5/10/20 收益与准确率
            ↓
   MCP: list_snapshots / get_snapshot / read_recent_memories / review_backtest
   Skills: 分析历史 / 决策记忆 / 快照跟踪对比
```

```
<项目根>/
├── user_config.json          # LLM / 数据源凭证（仓库之外，勿提交）
├── monitor.json              # watch 的规则与通知通道
├── trading_memory.log        # 决策记忆
├── memory/trading_memory.md
├── logs/                     # 每次运行的状态 JSON + 结果 JSON
├── reports/                  # HTML 报告（默认就会生成）
├── vector_memory/            # TF-IDF / chroma 索引
├── checkpoints/              # SQLite 检查点（--checkpoint 时）
├── monitor/                  # 盯盘事件台账
└── external_calibration/     # 外部校准台账（与内部记忆物理隔离）
```

## 附录 B：已知限制

| 限制 | 说明 |
|------|------|
| `analyze_stock` 是重操作 | 2–8 分钟、真实 token。别放进循环或高频触发 |
| 东方财富行情接口 | 按出口 IP 做服务端限流，被拦时自动切新浪/腾讯，报告表头会写实际出数的源 |
| `review_backtest` 依赖行情 | 复盘要取历史行情，同样受上面那条影响 |
| 复盘深度分析技能 | README 历史版本提到过 `skills/复盘深度分析`，**该目录当前不存在**，安装器不会安装它 |
| 仅供决策参考 | 本框架输出的是分析结论，**不执行任何交易**，也不构成投资建议 |
