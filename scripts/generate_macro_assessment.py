#!/usr/bin/env python3
"""
月度宏观环境评估生成器
采集宏观经济数据并生成结构化评估报告，保存到 macro_assessment.json。
供新闻分析师在个股分析时引用，避免每次重复分析宏观面。

用法:
    python3 generate_macro_assessment.py
"""

import json
import os
import sys
from datetime import datetime

OUTPUT_PATH = r"D:\stock\trading-agents\macro_assessment.json"


def get_market_indices() -> dict:
    """获取A股主要指数行情。"""
    try:
        import akshare as ak

        indices = {}
        # 主要宽基指数
        index_map = {
            "上证指数": "000001",
            "深证成指": "399001",
            "创业板指": "399006",
            "科创50": "000688",
            "沪深300": "000300",
            "中证500": "000905",
        }

        for name, code in index_map.items():
            try:
                df = ak.stock_zh_index_daily_em(symbol=f"sh{code}" if code.startswith("0000") or code.startswith("0003") or code.startswith("0009") else f"sz{code}")
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    prev = df.iloc[-2] if len(df) > 1 else latest
                    close = float(latest["close"])
                    change_pct = round((close - float(prev["close"])) / float(prev["close"]) * 100, 2)
                    indices[name] = {"close": close, "change_pct": change_pct}
            except Exception:
                pass

        return indices
    except ImportError:
        return {"error": "akshare not installed"}


def get_north_flow() -> dict:
    """获取北向资金近期流向。"""
    try:
        import akshare as ak

        df = ak.stock_hsgt_hist_em(symbol="沪股通")
        if df is not None and not df.empty:
            recent = df.tail(5)
            # 找到净流入列
            net_col = None
            for c in df.columns:
                if "净流入" in str(c) or "净买入" in str(c):
                    net_col = c
                    break
            if net_col:
                total_5d = sum(float(row[net_col]) for _, row in recent.iterrows())
                return {
                    "recent_5d_net_flow_billion": round(total_5d / 10000, 2),
                    "latest_date": str(recent.iloc[-1].iloc[0]) if len(recent) > 0 else "",
                }
    except Exception as e:
        return {"error": str(e)}
    return {}


def get_sector_performance() -> dict:
    """获取行业板块涨跌排行。"""
    try:
        import akshare as ak

        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            # 按涨跌幅排序
            if "涨跌幅" in df.columns:
                df_sorted = df.sort_values("涨跌幅", ascending=False)
                top_5 = df_sorted.head(5)[["板块名称", "涨跌幅"]].values.tolist()
                bottom_5 = df_sorted.tail(5)[["板块名称", "涨跌幅"]].values.tolist()
                return {
                    "top_gainers": [[str(n), round(float(v), 2)] for n, v in top_5],
                    "top_losers": [[str(n), round(float(v), 2)] for n, v in bottom_5],
                }
    except Exception as e:
        return {"error": str(e)}
    return {}


def get_market_sentiment() -> dict:
    """获取市场情绪指标（涨跌家数、涨停跌停等）。"""
    try:
        import akshare as ak

        # 涨跌停统计
        limit_up = ak.stock_zt_pool_em(date=datetime.now().strftime("%Y%m%d"))
        limit_down = ak.stock_zt_pool_dtgc_em(date=datetime.now().strftime("%Y%m%d"))

        return {
            "limit_up_count": len(limit_up) if limit_up is not None else 0,
            "limit_down_count": len(limit_down) if limit_down is not None else 0,
        }
    except Exception:
        return {}


def generate_assessment() -> dict:
    """生成完整的宏观评估报告。"""
    now = datetime.now()

    assessment = {
        "version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "valid_until": (now.replace(month=now.month + 1 if now.month < 12 else 1,
                                     year=now.year + (1 if now.month == 12 else 0))).isoformat(timespec="seconds"),
        "market_indices": get_market_indices(),
        "north_flow": get_north_flow(),
        "sector_performance": get_sector_performance(),
        "market_sentiment": get_market_sentiment(),
        # 以下字段由 AI agent 在 cron 任务中填充
        "macro_summary": "",
        "economic_cycle": "",  # 复苏/过热/滞胀/衰退
        "monetary_policy": "",  # 宽松/收紧/中性
        "fiscal_policy": "",  # 积极/稳健/紧缩
        "industry_outlook": "",  # 综合行业景气度判断
        "risk_factors": [],  # 主要风险因素列表
        "data_collection_note": "市场数据已自动采集，宏观判断部分需由AI分析补充。",
    }

    return assessment


def save_assessment(assessment: dict):
    """保存评估到 JSON 文件。"""
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(assessment, f, ensure_ascii=False, indent=2)
    print(f"Macro assessment saved to: {OUTPUT_PATH}")
    print(json.dumps({
        "generated_at": assessment["generated_at"],
        "indices_count": len(assessment.get("market_indices", {})),
        "has_north_flow": bool(assessment.get("north_flow")),
        "has_sectors": bool(assessment.get("sector_performance")),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    assessment = generate_assessment()
    save_assessment(assessment)
