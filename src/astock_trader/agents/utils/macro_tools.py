"""宏观评估读取工具 — 供新闻分析师引用月度宏观评估报告。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Annotated

from langchain_core.tools import tool

MACRO_PATH = r"D:\stock\trading-agents\macro_assessment.json"


@tool
def get_macro_assessment(
    dummy: Annotated[str, "无需参数，传任意值即可"] = "",
) -> str:
    """读取最新的月度宏观环境评估报告。

    返回宏观经济环境、市场指数、资金流向、行业景气度等结构化数据。
    此报告每月更新一次，在分析个股时应作为宏观背景参考。
    """
    if not os.path.exists(MACRO_PATH):
        return "[INFO] 暂无月度宏观评估报告。请先运行 generate_macro_assessment.py 生成报告。"

    try:
        with open(MACRO_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return f"[ERROR] 读取宏观评估文件失败: {e}"

    # 检查是否过期
    valid_until = data.get("valid_until", "")
    if valid_until:
        try:
            expiry = datetime.fromisoformat(valid_until)
            if datetime.now() > expiry:
                expired_note = f"\n\n> ⚠️ 本报告已过期（有效期至 {valid_until}），建议重新生成。"
            else:
                expired_note = f"\n\n> ✅ 报告有效期至 {valid_until}"
        except ValueError:
            expired_note = ""
    else:
        expired_note = ""

    # 格式化为可读文本
    lines = [
        f"# 月度宏观环境评估（{data.get('generated_at', '未知')}）",
        expired_note,
        "",
    ]

    # 宏观判断摘要
    if data.get("macro_summary"):
        lines.append(f"## 宏观摘要\n{data['macro_summary']}\n")
    if data.get("economic_cycle"):
        lines.append(f"**经济周期**: {data['economic_cycle']}")
    if data.get("monetary_policy"):
        lines.append(f"**货币政策**: {data['monetary_policy']}")
    if data.get("fiscal_policy"):
        lines.append(f"**财政政策**: {data['fiscal_policy']}")
    if data.get("industry_outlook"):
        lines.append(f"**行业景气度**: {data['industry_outlook']}")

    # 市场指数
    indices = data.get("market_indices", {})
    if indices and "error" not in indices:
        lines.append("\n## 市场指数")
        for name, info in indices.items():
            close = info.get("close", "—")
            chg = info.get("change_pct", "—")
            lines.append(f"- {name}: {close} ({chg:+.2f}%)")

    # 北向资金
    north = data.get("north_flow", {})
    if north and "error" not in north:
        lines.append(f"\n## 北向资金（近5日）\n- 净流入: {north.get('recent_5d_net_flow_billion', '—')}亿元")

    # 行业板块
    sectors = data.get("sector_performance", {})
    if sectors and "error" not in sectors:
        lines.append("\n## 行业板块表现")
        if sectors.get("top_gainers"):
            lines.append("**涨幅前5**: " + "、".join(f"{n}({v:+.2f}%)" for n, v in sectors["top_gainers"]))
        if sectors.get("top_losers"):
            lines.append("**跌幅前5**: " + "、".join(f"{n}({v:+.2f}%)" for n, v in sectors["top_losers"]))

    # 市场情绪
    sentiment = data.get("market_sentiment", {})
    if sentiment:
        lines.append(f"\n## 市场情绪\n- 涨停: {sentiment.get('limit_up_count', '—')}家 | 跌停: {sentiment.get('limit_down_count', '—')}家")

    # 风险因素
    risks = data.get("risk_factors", [])
    if risks:
        lines.append("\n## 主要风险因素")
        for r in risks:
            lines.append(f"- {r}")

    return "\n".join(lines)
