# 快照字段 Schema

数据文件：`D:\stock\trading-agents\analysis_log.json`

顶层结构：`{ "version": 1, "snapshots": [ ... ] }`

## 核心字段（v0.1）

| 字段 | 类型 | 说明 |
|------|------|------|
| `stock_code` | string | 6位A股代码，如 `"600519"` |
| `stock_name` | string | 中文名称，如 `"贵州茅台"` |
| `analysis_date` | string | 分析日期，`YYYY-MM-DD` 格式 |
| `analysis_price` | float \| null | 分析时股价，从报告中正则提取 |
| `rating` | string | 评级：`买入` / `增持` / `持有` / `减持` / `卖出` |
| `key_reasons` | list[string] | 关键理由（最多5条），来自投资辩论裁判判词 |
| `risk_points` | list[string] | 风险要点（最多3条），来自风控辩论裁判判词 |
| `elapsed_seconds` | float | 分析流水线执行耗时（秒） |
| `result_file` | string | 源结果 JSON 文件绝对路径 |
| `snapshot_time` | string | 快照创建时间，ISO-8601 |

## 回测跟踪字段（由「分析复盘」技能填充）

| 字段 | 类型 | 说明 |
|------|------|------|
| `track_t1` | object \| null | T+1 跟踪：`{date, price, change_pct, correct}` |
| `track_t5` | object \| null | T+5 跟踪 |
| `track_t10` | object \| null | T+10 跟踪 |
| `track_t20` | object \| null | T+20 跟踪 |
| `verified` | bool | 回测跟踪是否已完成 |
| `score` | float | 得分（0.0 或 100.0，基于方向正确性） |
| `score_detail` | string | 可读得分明细，如 `"+0.2% → +1.3% → +1.3% → +1.3%"` |

## 扩展字段（v0.3）

| 字段 | 类型 | 说明 |
|------|------|------|
| `analyst_signals` | object | 四份分析师报告的结构化信号。键为分析师类型（`市场/技术面`、`市场情绪`、`新闻舆情`、`基本面`），值含 `{rating, key_points, outlook}` |
| `debate_consensus` | object | 投资辩论共识：`{direction: "看多"/"看空"/"中性", confidence: "高"/"中"/"低", summary?: string}` |
| `confidence` | float | 辩论信心数值映射：高=0.9, 中=0.6, 低=0.3, 默认=0.5 |
| `key_assumptions` | list[string] | 关键假设（最多5条），从交易员计划和风控辩论中提取 |

## 对比字段（由 save_snapshot.py 自动生成）

仅当存在同标的历史快照时出现。

| 字段 | 类型 | 说明 |
|------|------|------|
| `previous_analysis` | object | 与最近一次历史分析的对比 |

`previous_analysis` 对象结构：

```json
{
  "prev_date": "2026-06-10",
  "prev_rating": "买入",
  "prev_score": 100.0,
  "prev_verified": true,
  "prev_correct": true,
  "rating_changed": true,
  "rating_shift": -1,
  "price_change_pct": -2.5,
  "interval_days": 6
}
```

| 子字段 | 说明 |
|--------|------|
| `prev_date` | 上次分析日期 |
| `prev_rating` | 上次评级 |
| `prev_score` | 上次得分（null 表示未验证） |
| `prev_verified` | 上次是否已完成回测验证 |
| `prev_correct` | 上次预测是否正确（score > 50 为正确；null 表示未验证） |
| `rating_changed` | 评级是否发生变化 |
| `rating_shift` | 评级档位变化（正=调升, 负=调降, 0=不变） |
| `price_change_pct` | 期间股价变动百分比 |
| `interval_days` | 两次分析间隔日历天数 |

## 跟踪摘要字段（由本技能注入）

仅当存在 ≥2 条同标的历史快照时注入。

| 字段 | 类型 | 说明 |
|------|------|------|
| `tracking_summary` | object | 多期跟踪汇总 |

`tracking_summary` 对象结构：

```json
{
  "total_analyses": 3,
  "date_range": "2026-06-10 ~ 2026-06-16",
  "rating_sequence": ["买入", "增持", "持有"],
  "rating_trend": "持续调降",
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
