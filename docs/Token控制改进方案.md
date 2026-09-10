# A股智能决策专家团 Token 控制改进方案

> **生成日期**: 2026-06-18  
> **调研范围**: GitHub 开源项目 12 个 + 学术论文 15 篇 + 工业最佳实践 6 篇  
> **目标**: 在不影响功能完整性和专家团性能的前提下，大幅降低 Token 消耗

---

## 1. 现状诊断

### 1.1 当前 Token 消耗画像

| 指标 | 当前值 |
|------|--------|
| 专家总数 | **11 个 LLM 节点（含分析师 4 + 研究员 2 + 经理 1 + 交易员 1 + 风控 3 + 基金经理 1）** |
| 单次完整运行输入 Token | **35,000 ~ 90,000** |
| 单次完整运行输出 Token | **3,500 ~ 8,000** |
| 单次 LLM 调用数 | **10 ~ 14 次** |
| 辩论轮数 | 多空 1 轮 + 风控 1 轮 |
| Max_tokens 限制 | **无** |
| 温度 | 全局统一 0.3 |
| 模型分层 | 四层（Deep / Heavy / Standard / Light） |

### 1.2 Token 消耗热点（按严重程度排序）

| 排名 | 热点 | 原因 | 单节点消耗 | 占总量比 |
|------|------|------|-----------|---------|
| 🔥1 | **基金经理** | 聚合全部报告+辩论+方案+风控 | 6K-15K 输入 | ~20% |
| 🔥2 | **看多/看空研究员** | 输入含 4 份完整报告 | 2× 3K-8K 输入 | ~18% |
| 🔥3 | **风控辩论（3节点）** | 各自接收全部上下文 | 3× 4K-10K 输入 | ~30% |
| 🔥4 | **基本面分析师** | 最多 10 个工具 + ReAct 循环 | 500-3K 输入 + 800-2K 输出 | ~10% |
| 🔥5 | **研究经理** | 4份报告 + 辩论总结 | 5K-12K 输入 | ~12% |

### 1.3 已有优化手段

| 手段 | 状态 | 效果 |
|------|------|------|
| `context_slimming`（上下文瘦身） | ✅ 已开启 | ~25% 节省 |
| 消息清理机制（分析师完成后） | ✅ 已开启 | 防止累积膨胀 |
| Headroom 提示压缩 | ⚠️ Windows 上关闭 | 如开启可达 60-95% |
| 辩论轮数 = 1 | ✅ 最低配 | 基线控制 |
| 四层模型分层 | ✅ 已配置 | 但未按任务复杂度路由 |
| 确定性报告生成 | ✅ 0 Token | 优秀设计 |

---

## 2. 可落地的改进方案

### 策略一：分层模型路由（Model Routing）—— **优先级：P0 🔥**

**现状问题**：虽然已经区分 Deep/Heavy/Standard/Light 四个层级，但所有任务统统调用 LLM。很多简单任务（如意图分类、报告摘要、风险等级判定）根本不需要完整推理。

**改进方案**：

| 任务复杂度 | 当前模型 | 建议模型 | 成本比 | 适用节点 |
|-----------|---------|---------|--------|---------|
| **极简任务** | Light LLM | 规则引擎/正则 | **0 Token** | 信号提取、评级解析 |
| **简单任务** | Light LLM | deepseek-v4-flash 或更小 | 1/10 | 报告摘要、关键信息提取 |
| **中等推理** | Standard LLM | deepseek-v4-pro 或等价 | 1/5 | 研究经理、交易员 |
| **复杂辩论** | Heavy LLM | 维持 | 1 | 看多/看空研究员 |
| **最终决策** | Deep LLM | 维持 | 1 | 基金经理 |

**具体落地措施**：

```python
# 在 trading_graph.py 的 _route_by_complexity() 中实现
TASK_COMPLEXITY_MAP = {
    "signal_extraction": "rule_engine",     # 正则/解析，0 Token
    "report_summary": "mini_model",         # deepseek-v4-flash
    "risk_assessment": "standard",          # 标准模型
    "debate_argument": "heavy",             # 强力推理
    "final_decision": "deep",               # 最强推理
}
```

**预期效果**：**节省 30-50%**（60-70% 的任务可用更小模型处理，业界数据支撑）

> 📊 **依据**：[Zylos Research](https://zylos.ai/research/2026-04-12-ai-agent-cost-optimization-token-budget-model-routing/) 研究显示 "60-70% 的 Agent 调用适合小模型"；[TradingAgents](https://github.com/TauricResearch/TradingAgents) 项目已采用 Deep Think / Quick Think 双模型策略。

---

### 策略二：Prompt 压缩与上下文窗口管理 —— **优先级：P0 🔥**

**现状问题**：
- 4 份分析师报告（每份 500-2000 字符）原封不动传给研究员和基金经理
- 系统提示词重复注入，无缓存复用
- 风控 3 节点接收几乎相同的完整上下文
- Headroom 在 Windows 上不可用

**改进方案 A：摘要式上下文传递（对标 Anthropic Harness Engineering）**

| 节点 | 当前传递 | 建议传递 | 节省 |
|------|---------|---------|------|
| 研究员 | 4 份完整报告 | 报告摘要 + 关键指标表 | **50-60%** |
| 基金经理 | 全部上下文 | 结构化决策矩阵 + 精简摘要 | **60-70%** |
| 风控三节点 | 完整上下文 ×3 | 共享上下文 + 各自视角补充 | **40-50%** |

具体实现：用 Light 模型将分析师报告压缩为结构化摘要，只保留：
- 核心结论（1 句）
- 关键数据（数值表格）
- 风险/机会（各 ≤3 条）
- 置信度（0-1）

```python
# 在 context_slimmer.py 中增加 summarize_by_agent() 方法
def summarize_report(report: str, agent: str) -> dict:
    """用 cheap model 将 2000 字报告压缩为 200 字结构化摘要"""
    return {
        "conclusion": "...",     # ≤50 字
        "key_metrics": {...},    # 数值表
        "risks": [...],          # ≤3 条
        "confidence": 0.0-1.0
    }
```

> 📊 **依据**：[TradingAgents](https://github.com/TauricResearch/TradingAgents) 使用结构化输出减少重试消耗；[Anthropic Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) 提出"只传递结构化摘要，而非完整转录"。

**改进方案 B：系统提示词前缀缓存**

所有 agent 共享大量相同的系统提示词前缀（角色定义、交易规则、输出格式等）。利用 LLM provider 的前缀缓存机制：

| Provider | 缓存折扣 | 机制 |
|----------|---------|------|
| DeepSeek | **98%** | 磁盘 KV Cache |
| Anthropic | 90% | Prompt Caching |
| OpenAI | 50% | 自动缓存 |

实现方式：将系统提示词作为固定前缀，所有 agent 调用共享。

```python
# 统一系统提示词前缀（可缓存部分）
SYSTEM_PREFIX = """
你是一位A股投资分析专家。交易规则：
1. 中国股市涨为红色、跌为绿色
2. T+1 交易制度...
3. 涨跌停 10%...（ST 5%）
"""
# 各 Agent 特有部分追加
AGENT_SPECIFIC = {
    "market_analyst": "你的专长是技术分析...",
    ...
}
```

**预期效果**：
- 前缀缓存：**50-98% 输入 Token 节省**
- 摘要传递：**40-60% 上下文 Token 节省**  
- 综合：**50-70% 总节省**

> 📊 **依据**：[awesome-llm-token-optimization](https://github.com/pleasedodisturb/awesome-llm-token-optimization) 汇总：Anthropic 90%、OpenAI 50%、DeepSeek 98% 缓存折扣。

---

### 策略三：语义缓存（Semantic Cache）—— **优先级：P1 🔥**

**现状问题**：同一股票多次分析时，分析师产出的报告高度相似（财务数据变化慢、技术形态接近），但每次都要重新调用 LLM。

**改进方案**：集成 [GPTCache](https://github.com/zilliztech/GPTCache) 或自建语义缓存层

```python
# 架构：在 llm_clients/ 中增加 semantic_cache.py
class SemanticCache:
    """语义缓存层，拦截重复/相似查询"""
    
    def __init__(self):
        self.embedding_model = "text-embedding-3-small"  # 便宜
        self.similarity_threshold = 0.92  # 高阈值保证质量
        self.ttl = 3600  # 1 小时过期
    
    def get_or_compute(self, query: str, compute_fn):
        """相似度 > 0.92 时直接返回缓存"""
        ...
```

适用场景：
- 同一股票 1 小时内的重复分析 → 缓存命中率 30-50%
- 同行业股票的分析框架相似 → 部分复用
- 市场静态时期的日常分析 → 高命中率

**预期效果**：**缓存命中率 30-40%，对应 Token 节省 30-40%**

> 📊 **依据**：[GPTCache](https://github.com/zilliztech/GPTCache) 生产数据：相似度阈值 0.9 时缓存命中率 20-40%；[Zylos](https://zylos.ai/research/2026-04-12-ai-agent-cost-optimization-token-budget-model-routing/) 指出 "31% 的 LLM 查询存在语义相似性"。

---

### 策略四：工具调用优化 —— **优先级：P1**

**现状问题**：
- 基本面分析师加载 **10 个工具**的全部描述，每次 LLM 调用都传入
- ReAct 循环中，中间结果（数据库返回的原始 JSON）全部进入上下文
- 工具描述中存在冗余修辞

**改进方案**：

**A. 工具描述精简化**

```python
# 当前（冗余）
{
    "name": "get_financial_statements",
    "description": "获取公司的财务报表数据，包括资产负债表、利润表、现金流量表三大报表。这个工具可以帮助你全面了解公司的财务状况、盈利能力、偿债能力和现金流水平。使用前请确保输入正确的股票代码格式。"
}

# 优化后（精简）
{
    "name": "get_financial_statements",
    "description": "获取三大报表(资产/利润/现金)。输入: stock_code 股票代码"
}
```
**节省：50-70% 工具描述 Token**

**B. 工具结果过滤**

```python
# 在 core_stock_tools.py 中增加 result_filter()
def filter_tool_result(raw_json: dict, max_fields: int = 20) -> dict:
    """只保留 Top-N 关键字段，丢弃冗余嵌套"""
    ...
```
**节省：40-60% 工具返回 Token**

**C. 智能工具选择**

```python
# 根据当前任务只加载相关工具，而非全部 10 个
TASK_TOOLS_MAP = {
    "profitability": ["get_income_stmt", "get_financial_ratios"],
    "valuation": ["get_valuation", "get_peers_comparison"],
    "industry_chain": ["get_industry_chain", "get_competitors"],
}
```

> 📊 **依据**：[Anthropic Token-Efficient Tool Use](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/token-efficient-tool-use) 实现输出减少 70%；[Anthropic Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use) 通过工具搜索减少 85% Token。

---

### 策略五：输出 Token 控制 —— **优先级：P1**

**现状问题**：
- **所有节点无 `max_tokens` 限制**，完全依赖模型默认值
- 研究员和基金经理有时生成长篇大论，超出实际需要
- 结构化输出虽然已配置，但降级为自由文本时无长度控制

**改进方案**：

| 节点 | 建议 max_tokens | 理由 |
|------|----------------|------|
| 技术/情绪分析师 | 800 | 技术报告无需过长 |
| 新闻/基本面分析师 | 1500 | 需要较多数据呈现 |
| 看多/看空研究员 | 1000 | 辩论论点聚焦即可 |
| 研究经理 | 1000 | 综合判断 |
| 交易员 | 600 | 交易计划精炼 |
| 风控三节点 | 600 | 风险评估聚焦 |
| 基金经理 | 1200 | 最终决策需完整 |

```python
# 在 default_config.py 中增加
AGENT_MAX_TOKENS = {
    "market_analyst": 800,
    "social_media_analyst": 800,
    "news_analyst": 1500,
    "fundamentals_analyst": 1500,
    "bull_researcher": 1000,
    "bear_researcher": 1000,
    "research_manager": 1000,
    "trader": 600,
    "aggressive_debator": 600,
    "conservative_debator": 600,
    "neutral_debator": 600,
    "portfolio_manager": 1200,
}
```

**预期效果**：**输出 Token 节省 40-60%**（从平均 600-1000 降至 400-800）

> 📊 **依据**：[Agent Token Optimization Guide](https://www.daoyuly.cn/2026/2026-04-15-agent-token-optimization-guide/) 实战案例：代码审查 Agent 通过结构化输出节省 66%，客服 Agent 节省 64%。

---

### 策略六：Agent 自感知预算（Agent-Aware Budget）—— **优先级：P2**

**现状问题**：Agent 完全不知道自己的 Token 消耗，可能陷入无意义的 ReAct 死循环或生成冗余内容。

**改进方案**：向 Agent 上下文注入剩余 Token 预算信息

```python
# 在 trading_graph.py 的 _invoke_agent() 中增加
def inject_budget_context(state: AgentState):
    remaining = state.token_budget - state.token_spent
    if remaining < 2000:
        budget_note = f"⚠️ 剩余 Token: {remaining}。请精炼输出，优先给出核心结论。"
    else:
        budget_note = f"剩余 Token: {remaining}"
    return budget_note
```

效果：
- Agent 在预算紧张时自动精炼输出
- 避免无意义的长篇展开
- 预算耗尽时生成部分结果而非完全失败

> 📊 **依据**：[Zylos Research](https://zylos.ai/research/2026-04-12-ai-agent-cost-optimization-token-budget-model-routing/)："Agent 知道剩余预算时，会摘要早期工作而非重新阅读、更早决策、预算接近耗尽时升级给人类"。

---

### 策略七：批量推理（Batch Inference）—— **优先级：P2**

**现状问题**：4 个分析师串联执行，但它们是**完全独立**的——技术面、情绪、新闻、基本面分析不相互依赖。

**改进方案**：将 4 个分析师改为并行执行

```python
# 当前（串联）：技术面 → 情绪 → 新闻 → 基本面
# 改进（并行）：[技术面 ‖ 情绪 ‖ 新闻 ‖ 基本面] → 合并 → 研究员

# 在 setup.py 中修改 graph 构建
workflow.add_node("parallel_analysts", run_parallel_analysts)
workflow.add_edge(START, "parallel_analysts")
workflow.add_edge("parallel_analysts", "bull_researcher")
```

配合 Batch API（如果 provider 支持），4 个分析师调用可以批量处理，享受 50% 折扣。

**预期效果**：
- 延迟降低 60-75%（4 个并行 vs 串联）
- 配合 Batch API：**额外节省 50% Token 费用**

> 📊 **依据**：[Batch API 官方定价](https://platform.openai.com/docs/guides/batch) 50% 折扣；vLLM 持续批处理实现高达 23x 吞吐改进。

---

## 3. 分阶段实施路线图

### Phase 1（1-2 周）：快速见效 — 预计节省 35-45%

| # | 措施 | 实施难度 | 预期节省 |
|---|------|---------|---------|
| 1 | **添加 max_tokens 限制** | ⭐ 极低 | 输出 40-60% |
| 2 | **分析师并行执行** | ⭐ 极低 | 延迟 60-75% |
| 3 | **精简工具描述** | ⭐ 极低 | 工具 50-70% |
| 4 | **系统提示词前缀缓存** | ⭐⭐ 低 | 输入 50-98% |
| 5 | **工具结果过滤** | ⭐⭐ 低 | 工具返回 40-60% |

### Phase 2（2-4 周）：智能优化 — 累计节省 55-70%

| # | 措施 | 实施难度 | 预期节省 |
|---|------|---------|---------|
| 6 | **摘要式上下文传递** | ⭐⭐⭐ 中 | 上下文 40-60% |
| 7 | **分层模型路由（按任务）** | ⭐⭐⭐ 中 | 模型成本 30-50% |
| 8 | **语义缓存集成（GPTCache）** | ⭐⭐⭐ 中 | 重复查询 100% |
| 9 | **智能工具选择（按任务）** | ⭐⭐ 低 | 工具描述 60-80% |

### Phase 3（4-8 周）：深度优化 — 累计节省 70-85%

| # | 措施 | 实施难度 | 预期节省 |
|---|------|---------|---------|
| 10 | **Agent 自感知预算** | ⭐⭐⭐ 中 | 综合 5-10% |
| 11 | **LLMLingua 提示压缩** | ⭐⭐⭐⭐ 高 | 上下文 5-20x |
| 12 | **知识图谱替代全文检索** | ⭐⭐⭐⭐⭐ 很高 | RAG 60-80% |
| 13 | **Headroom 跨平台支持** | ⭐⭐⭐⭐ 高 | 上下文 60-95% |

---

## 4. 对比分析：优化前后

| 指标 | 优化前 | Phase 1 | Phase 2 | Phase 3 |
|------|--------|---------|---------|---------|
| 输入 Token | 35K-90K | 18K-45K | 10K-25K | 5K-15K |
| 输出 Token | 3.5K-8K | 2K-5K | 1.5K-3.5K | 1K-2.5K |
| 总 Token | 40K-100K | 20K-50K | 12K-30K | 6K-18K |
| 单次成本（DeepSeek） | ¥0.04-0.10 | ¥0.02-0.05 | ¥0.012-0.03 | ¥0.006-0.018 |
| 延迟（串行） | 30-60s | 15-30s | 10-20s | 5-15s |
| **累计节省** | — | **~50%** | **~70%** | **~85%** |

> 成本基于 DeepSeek V4 定价（输入 ¥1/百万 Token，输出 ¥2/百万 Token）

---

## 5. 质量保障措施

> ⚠️ **核心原则：Token 优化绝不牺牲分析质量**

### 5.1 回归测试套件

```python
# 建立分析质量基准
BASELINE_METRICS = {
    "rating_accuracy": 0.0,   # 对比历史评级
    "report_coverage": 0.0,   # 报告覆盖的关键维度
    "decision_confidence": 0.0,  # 决策置信度分布
}
# 每次优化后自动运行对比
```

### 5.2 A/B 对比机制

```
旧管线（完整版）──┐
                  ├── 对比分析报告
新管线（优化版）──┘
```

### 5.3 质量红线

| 指标 | 红线 | 触发动作 |
|------|------|---------|
| 评级一致性 | 下降 > 10% | 回滚优化 |
| 报告完整度 | 下降 > 15% | 审查压缩策略 |
| 关键数据遗漏 | > 1 条/报告 | 调整摘要提取器 |

---

## 6. 参考项目清单

### 核心参考项目

| 项目 | GitHub | 核心借鉴点 |
|------|--------|-----------|
| **LLMLingua** | [microsoft/LLMLingua](https://github.com/microsoft/LLMLingua) | 20x 提示压缩，预算控制器 |
| **GPTCache** | [zilliztech/GPTCache](https://github.com/zilliztech/GPTCache) | 语义缓存，30%+ 命中率 |
| **TradingAgents** | [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | Deep/Quick Think 分层，结构化输出 |
| **LiteLLM** | [BerriAI/litellm](https://github.com/BerriAI/litellm) | 100+ LLM 统一路由 |
| **RouteLLM** | [lm-sys/RouteLLM](https://github.com/lm-sys/RouteLLM) | 智能模型路由 |
| **awesome-llm-token-optimization** | [pleasedodisturb/awesome-llm-token-optimization](https://github.com/pleasedodisturb/awesome-llm-token-optimization) | Token 优化知识库汇总 |

### 学术参考

| 论文 | 年份 | 核心贡献 |
|------|------|---------|
| LLMLingua (EMNLP'23) | 2023 | Token 级迭代压缩，最高 20x |
| LLMLingua-2 (ACL'24) | 2024 | BERT 蒸馏加速版，快 3-6x |
| LongLLMLingua | 2023 | 长上下文扩展，4x 更少 Token，性能提升 21.4% |
| 500xCompressor | 2024 | 极致压缩：6-480x |
| LoPace | 2026 | 无损压缩，72.2% 节省，100% 重建 |
| Lost in the Middle | 2023 | 模型难以处理中间位置信息 |
| Self-Route (ACL'24) | 2024 | 自适应 RAG + 长上下文切换 |
| Tokenomics | 2026 | Agent 软件工程 Token 消耗分析 |

---

## 7. 总结

这个专家团目前的 Token 消耗属于「**能跑但像喝油一样**」——单次分析烧 4-10 万 Token，每次调用 10-14 次 LLM，还没设 max_tokens 限制。好消息是优化空间巨大。

按照这个方案分三步走：
- **Phase 1**（2周内）：加 max_tokens、分析师并行、精简工具描述、缓存前缀——**省一半**
- **Phase 2**（1个月内）：摘要传递、模型路由、语义缓存——**省七成**
- **Phase 3**（2个月内）：提示压缩、Agent 自感知、知识图谱——**省八成以上**

而且这些改进**不影响任何一个专家的分析能力**——该看财报的还看财报，该辩论的还辩论，该风控的还风控。只是把传输方式从「全文电报」升级为「结构化摘要」，把模型选择从「一把梭」升级为「分级调度」。

参考的 TradingAgents 项目已经证明这种分层架构在生产环境下可行，LLMLingua 和 GPTCache 都是微软和 Zilliz 的成熟开源项目，不是实验室玩具。
