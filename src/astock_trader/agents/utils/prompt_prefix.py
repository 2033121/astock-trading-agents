"""Shared system prefix — one constant opening for every LLM node.

Every node prepends :data:`SYSTEM_PREFIX` to its system prompt (or uses it as
its system message).  Because the exact same text precedes *all* node calls,
industry providers can reuse the cached KV block across nodes and requests
(DeepSeek disk KV cache discount ~90%+, OpenAI 50%); see
``docs/Token控制改进方案.md`` strategy 2B.

Editing rules
-------------
* Keep the prefix byte-stable: any change dissolves the cache on the next run
  (one extra cold request, acceptable, but update CHANGELOG when you do).
* Keep it role-neutral and dated-neutral — never embed stock names, dates,
  or prices here; those belong in the per-node human prompt.
"""

from __future__ import annotations

SYSTEM_PREFIX = """你是一个面向中国A股的量化投资决策系统中的分析节点，请始终遵守以下共同规则：

【交易制度】
1. A股实行 T+1 交易：当日买入的股票次一交易日才能卖出；当日卖出股票的资金可继续买入。
2. 交易时段为 9:30-11:30、13:00-15:00；停牌、复牌与新股上市首日规则以交易所披露为准。
3. 涨跌幅限制：主板 ±10%，ST 股 ±5%，创业板/科创板 ±20%，北交所 ±30%。
4. 涨跌着色遵循 A 股惯例：红色代表上涨，绿色代表下跌。

【分析纪律】
5. 结论只基于给定数据与工具结果；数据缺失时明确写"数据不足"，不得编造数值。
6. 区分事实与推测：事实需引用具体数据，推测须标注"假设"。
7. 全程使用中文，简明有条理；涉及的评级仅可取：买入/增持/持有/减持/卖出。"""

__all__ = ["SYSTEM_PREFIX"]
