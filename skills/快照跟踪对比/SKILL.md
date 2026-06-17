---
name: astock-snapshot-tracking-comparison
description: 对同一只A股的多次分析快照进行跟踪对比。在保存新快照前自动检测历史快照并附加 previous_analysis 对比字段；支持用户主动查询某只股票的全部分析历史，呈现评级/得分/价格演变轨迹和方向一致性判断。触发词：快照对比、跟踪分析、分析历史对比、这只股票之前分析过吗、快照跟踪、snapshot tracking、重复分析对比、之前给过什么评级、历史评级、评级变化、方向一致性。
version: 1.0.0
---

# A股快照跟踪对比

本技能是对 `save_snapshot.py` 已有单点对比逻辑（`find_previous_analysis` + `build_comparison`）的**增强层**，提供两个核心能力：

- **工作流 A（保存时增强）**：在 `astock-analysis-report-workflow` Step 4 执行前后，检测多期历史快照并生成 `tracking_summary`，使重复分析变成有深度的跟踪观察。
- **工作流 B（主动查询）**：用户随时可查询某只股票的全部分析历史，获得评级/价格/方向的演变全景。

## 数据源

所有数据来自 `D:\stock\trading-agents\analysis_log.json`，结构为：

```json
{
  "version": 1,
  "snapshots": [ { ...snapshot... }, ... ]
}
```

每条快照的完整字段定义见 [reference/snapshot-schema.md](reference/snapshot-schema.md)。评级五级量表见 [reference/rating-scale.md](reference/rating-scale.md)。

---

## 工作流 A：保存时对比增强

### 触发时机

本工作流嵌入 `astock-analysis-report-workflow` 的 Step 4（自动保存快照）。在执行 `save_snapshot.py` **之前**运行。

### 步骤

#### A1. 读取历史快照

```python
# 伪代码 — agent 用 Python 或直接在 bash 中执行
import json
with open(r"D:\stock\trading-agents\analysis_log.json", "r", encoding="utf-8") as f:
    log = json.load(f)
history = [s for s in log["snapshots"] if s["stock_code"] == "{target_stock_code}"]
history.sort(key=lambda s: s["analysis_date"])
```

#### A2. 判断快照数量并生成 tracking_summary

| 历史快照数 | 处理方式 |
|-----------|---------|
| 0 条 | 首次分析，无需对比。`save_snapshot.py` 本身不会添加 `previous_analysis` 字段，正常保存即可。 |
| 1 条 | `save_snapshot.py` 已自动处理 `previous_analysis` 单点对比，正常保存即可。 |
| ≥2 条 | **进入增强模式**：除 `save_snapshot.py` 自动生成的 `previous_analysis` 外，agent 额外构建 `tracking_summary` 对象（见下）。 |

#### A3. 构建 tracking_summary（仅 ≥2 条历史快照时）

```json
{
  "total_analyses": 3,
  "date_range": "2026-06-10 ~ 2026-06-16",
  "rating_sequence": ["买入", "增持", "持有"],
  "rating_trend": "连续调降",
  "direction_consistency": "由多转空",
  "cumulative_price_change_pct": -5.2,
  "avg_confidence": 0.63,
  "verified_accuracy": "1/2 (50%)",
  "key_reasons_evolution": [
    "6/10: 业绩超预期+资金流入",
    "6/13: 业绩兑现但估值偏高",
    "6/16: 估值压力+资金流出"
  ]
}
```

各字段计算规则：

- **rating_sequence**：按日期排序的评级列表
- **rating_trend**：根据 `rating_shift` 序列判断
  - 全部 ≥0 → "持续调升" 或 "维持不变"
  - 全部 ≤0 → "持续调降" 或 "维持不变"
  - 有正有负 → "反复摇摆"
- **direction_consistency**：根据评级映射方向（买入/增持=看多，减持/卖出=看空，持有=中性）
  - 全部看多 → "持续看多"
  - 全部看空 → "持续看空"
  - 看多→看空 → "由多转空"
  - 看空→看多 → "由空转多"
  - 含中性穿插 → "方向摇摆"
- **cumulative_price_change_pct**：`(最新价格 - 首次价格) / 首次价格 * 100`
- **avg_confidence**：所有历史快照 `confidence` 字段的均值
- **verified_accuracy**：已验证快照中预测正确的比例（`score > 50` 为正确）
- **key_reasons_evolution**：每次分析的 `key_reasons[0]`（第一条理由），带日期前缀

#### A4. 注入 tracking_summary 到新快照

`save_snapshot.py` 保存后，重新读取 `analysis_log.json`，找到刚写入的快照（同 stock_code + analysis_date），将 `tracking_summary` 追加进去，再写回文件。

```bash
cd C:/Users/xing/.qoderworkcn/plugins-custom/astock-trading-agents
python -c "
import json
LOG = r'D:\stock\trading-agents\analysis_log.json'
with open(LOG, 'r', encoding='utf-8') as f:
    log = json.load(f)
# 找到刚保存的快照并注入 tracking_summary
for s in log['snapshots']:
    if s['stock_code'] == '{code}' and s['analysis_date'] == '{date}':
        s['tracking_summary'] = {tracking_summary_dict}
        break
with open(LOG, 'w', encoding='utf-8') as f:
    json.dump(log, f, ensure_ascii=False, indent=2)
"
```

#### A5. 结果报告中的对比段落

当 `save_snapshot.py` 输出包含 `comparison` 字段时，**必须**在结果报告中包含对比段落。模板：

```
与历史分析对比（{prev_date}）：上次给"{prev_rating}"，本次{rating_shift_label}为"{current_rating}"。
期间股价变动 {price_change_pct}。上次预测{prev_correct_label}。
```

当存在 `tracking_summary` 时，追加一段：

```
跟踪观察（累计 {total_analyses} 次分析）：评级轨迹 {rating_sequence_str}，
方向判断{direction_consistency}，累计价格变动 {cumulative_price_change_pct:+.1f}%。
核心逻辑从"{first_reason}"演变为"{last_reason}"。
```

若 `prev_correct` 为"错误"，需额外添加一句反思：

```
上次教训：{根据 key_reasons 和 price_change 简要分析上次判断失误的原因}。
```

---

## 工作流 B：主动查询跟踪对比

### 触发条件

用户提到某只股票（名称或代码）+ 以下任一意图信号：

- "之前分析过吗"、"分析历史"、"跟踪对比"、"快照对比"
- "之前给过什么评级"、"评级变化"、"历史评级"
- "这只股票的分析演变"、"方向一致性"
- "snapshot tracking"、"tracking comparison"

### 步骤

#### B1. 解析标的

从用户消息中提取股票名称或代码。如果是名称，先在 `analysis_log.json` 中按 `stock_name` 模糊匹配；找不到时查 `save_snapshot.py` 中的 `STOCK_NAMES` 映射或通过 akshare 查找代码。

#### B2. 筛选并排序快照

```python
import json
with open(r"D:\stock\trading-agents\analysis_log.json", "r", encoding="utf-8") as f:
    log = json.load(f)
snapshots = [s for s in log["snapshots"] if s["stock_code"] == "{code}"]
snapshots.sort(key=lambda s: s["analysis_date"])
```

若无记录，告知用户"该股票尚无分析记录，可通过智能分析功能首次分析"。

#### B3. 生成跟踪报告

以下为输出模板：

```markdown
## {stock_name}（{stock_code}）分析跟踪

共 {count} 次分析，时间跨度 {first_date} ~ {last_date}

| 日期 | 评级 | 价格 | 较上次涨跌 | 信心 | 已验证 | 预测正确 |
|------|------|------|-----------|------|--------|---------|
| 2026-06-10 | 买入 | 1800.00 | — | 0.9 | 是 | 正确 |
| 2026-06-13 | 增持 | 1785.00 | -0.8% | 0.6 | 是 | 错误 |
| 2026-06-16 | 持有 | 1760.00 | -1.4% | 0.6 | 否 | — |

### 评级演变
买入 → 增持 → 持有（持续调降）

### 方向一致性
由多转空：从最初看多（买入）逐步转向中性（持有）

### 累计表现
首次分析至今价格变动：-2.2%

### 预测准确率
已验证 2 次，正确 1 次（50%）

### 核心逻辑演变
- 6/10：业绩超预期，资金持续流入，技术面强势突破
- 6/13：业绩兑现预期，但估值压力显现，资金开始分歧
- 6/16：估值高位承压，主力资金流出，技术面转弱

### 点评
{agent 根据以上数据给出 2-3 句简要点评，关注评级变化的合理性、方向一致性对投资纪律的参考价值}
```

#### B4. 输出方式

- 在对话中直接呈现报告
- 如果用户通过 IM 渠道请求，使用 `qoder_delegate_to_im` 发送

---

## 与已有技能的协作关系

| 技能 | 职责 | 本技能如何协作 |
|------|------|--------------|
| 智能分析 | 运行分析、提取快照字段 | 本技能在其 Step 4 嵌入，增强对比逻辑 |
| astock-analysis-report-workflow | 强制快照必存、主动推送 | 本技能在 Step 4 前后注入 tracking_summary |
| 分析复盘 | T+1~T+20 回测准确率 | 本技能读取其写入的 `verified`/`score` 字段来计算准确率 |
| 分析历史 | 查看全部快照列表 | 本技能提供单股深度跟踪视角，分析历史提供全局视角 |

---

## 注意事项

1. **仅有一条快照时不生成对比**：提示"首次分析，暂无历史对比数据"
2. **analysis_log.json 不存在或为空**：提示用户运行首次分析
3. **不修改 save_snapshot.py 源码**：本技能在 agent 层面做增强，通过保存后注入 `tracking_summary` 字段实现，不侵入脚本
4. **方向映射规则**：买入/增持 → 看多；减持/卖出 → 看空；持有 → 中性
5. **预测正确性判断**：`verified=true` 且 `score > 50` 视为方向正确
6. **数据仅供研究参考，不构成投资建议**
