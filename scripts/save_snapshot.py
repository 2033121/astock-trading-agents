#!/usr/bin/env python3
"""
分析快照保存工具
从 astock-trader 分析结果 JSON 中提取关键信息，追加到 analysis_log.json。

用法:
    python save_snapshot.py <result_json_path>

示例:
    python save_snapshot.py C:\\Users\\xing\\.astock_trader\\logs\\600519_2026-06-10_result.json
"""

import json
import re
import sys
import os
from datetime import datetime

LOG_PATH = r"D:\stock\trading-agents\analysis_log.json"

# 股票名称映射（常用，可通过 akshare 动态获取）
STOCK_NAMES = {
    "600519": "贵州茅台",
    "000155": "川能动力",
    "003022": "联泓新科",
    "000001": "平安银行",
    "600036": "招商银行",
    "601318": "中国平安",
    "000858": "五粮液",
    "002594": "比亚迪",
    "300750": "宁德时代",
    "600900": "长江电力",
}


def _parse_price(raw: str) -> float | None:
    """解析价格字符串，处理千分位逗号。"""
    try:
        return float(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def extract_price(text: str) -> float | None:
    """从文本中提取股价，尝试多种模式（含千分位逗号）。"""
    if not text:
        return None

    # 价格数字模式（支持千分位逗号，如 1,275.88）
    NUM = r"([\d,]+\.?\d*)"

    patterns = [
        rf"当前价位[（(]约?{NUM}元[）)]",
        rf"当前股价[（(]约?{NUM}元[）)]",
        rf"当前股价{NUM}元",
        rf"当前价(?:格|位)[：:]\s*{NUM}\s*元",
        rf"当前价位（{NUM}元附近）",
        rf"最新收盘价[（(].*?[）)]\s*\|\s*{NUM}\s*元",
        rf"收盘[价價][：:]\s*{NUM}",
        rf"最新价[：:]\s*{NUM}",
        rf"约{NUM}元",
    ]

    for pat in patterns:
        m = re.search(pat, text)
        if m:
            price = _parse_price(m.group(1))
            if price and price > 0:
                return price
    return None


def extract_key_reasons(debate_text: str, max_reasons: int = 5) -> list[str]:
    """从辩论裁判判词中提取关键理由。"""
    if not debate_text:
        return []

    reasons = []

    # 方法1：提取编号列表项，处理多种格式
    # 匹配: 1. **bold**: content  或  1. plain: content  或  1️⃣ content
    numbered = re.findall(
        r"(?:\d+[.、．]|[①②③④⑤⑥⑦⑧⑨⑩])\s*\*{0,2}(.+?)[：:]\s*(.+?)(?:\n|$)",
        debate_text,
    )
    for title, content in numbered:
        # 去除 markdown 标记
        title = re.sub(r"\*{1,2}", "", title).strip()
        content = re.sub(r"\*{1,2}", "", content).strip()
        # 优先用标题作为理由摘要
        if title and len(title) > 5:
            reasons.append(title[:120])
        elif content and len(content) > 10:
            reasons.append(content[:120])
        if len(reasons) >= max_reasons:
            break

    # 方法2：如果没找到编号列表，尝试提取"投资逻辑"段落
    if not reasons:
        logic_match = re.search(r"投资逻辑\*{0,2}[：:]?\s*\n((?:.+\n?){1,8})", debate_text)
        if logic_match:
            lines = logic_match.group(1).strip().split("\n")
            for line in lines[:max_reasons]:
                clean = re.sub(r"^\d+[.、]\s*\*{0,2}", "", line.strip())
                clean = re.sub(r"\*{1,2}", "", clean)[:120]
                if len(clean) > 10:
                    reasons.append(clean)

    # 方法3：如果还没有，尝试提取 "评级"/"执行摘要" 后的内容
    if not reasons:
        summary_match = re.search(r"执行摘要[：:]\s*(.+?)(?:\n\n|$)", debate_text, re.DOTALL)
        if summary_match:
            reasons.append(summary_match.group(1).strip()[:200])

    return reasons


def extract_stock_name(code: str, text_fields: list[str]) -> str:
    """尝试获取股票名称。"""
    # 先从已知映射查
    if code in STOCK_NAMES:
        return STOCK_NAMES[code]

    # 从文本中尝试提取 "代码 名称" 或 "名称（代码）" 模式
    for text in text_fields:
        if not text:
            continue
        # 匹配 "600519 贵州茅台" 或 "贵州茅台（600519）" 等模式
        m = re.search(rf"{code}\s+([\u4e00-\u9fa5]{{2,6}})", text)
        if m:
            return m.group(1)
        m = re.search(rf"([\u4e00-\u9fa5]{{2,6}})[（(]{code}[）)]", text)
        if m:
            return m.group(1)

    return code


def extract_analyst_signals(result: dict) -> dict:
    """从四份分析师报告中提取结构化信号摘要。"""
    signals = {}
    report_map = {
        "market_report": "市场/技术面",
        "sentiment_report": "市场情绪",
        "news_report": "新闻舆情",
        "fundamentals_report": "基本面",
    }
    for field, label in report_map.items():
        text = result.get(field, "")
        if not text:
            continue
        signal = {}
        # trend detection
        bullish_kw = any(kw in text for kw in ["上涨趋势", "看多", "偏多", "强势", "突破", "放量上涨", "利好", "超预期", "资金流入"])
        bearish_kw = any(kw in text for kw in ["下跌趋势", "看空", "偏空", "弱势", "破位", "放量下跌", "利空", "不及预期", "资金流出"])
        if bullish_kw and not bearish_kw:
            signal["rating"] = "正面"
        elif bearish_kw and not bullish_kw:
            signal["rating"] = "负面"
        else:
            signal["rating"] = "中性"
        # numbered points
        points = re.findall(r"(?:\d+[.、]|[•\-\*])\s*(.{10,80})", text)
        signal["key_points"] = [p.strip() for p in points[:3]]
        # outlook
        if any(kw in text for kw in ["前景乐观", "增长预期", "向好", "改善"]):
            signal["outlook"] = "偏多"
        elif any(kw in text for kw in ["前景堪忧", "下滑", "恶化", "风险较大"]):
            signal["outlook"] = "偏空"
        else:
            signal["outlook"] = "中性"
        signals[label] = signal
    return signals


def extract_debate_consensus(result: dict) -> dict:
    """从投资辩论裁判判词中提取共识方向。"""
    debate = result.get("investment_debate_state", {})
    if not isinstance(debate, dict):
        return {}
    judge = debate.get("judge_decision", "")
    if not judge:
        return {}
    consensus = {}
    if any(kw in judge for kw in ["买入", "增持", "看多", "偏多"]):
        consensus["direction"] = "看多"
    elif any(kw in judge for kw in ["卖出", "减持", "看空", "偏空"]):
        consensus["direction"] = "看空"
    else:
        consensus["direction"] = "中性"
    strong = any(kw in judge for kw in ["强烈", "非常", "高度确信", "明确"])
    weak = any(kw in judge for kw in ["不确定", "存在分歧", "较弱"])
    consensus["confidence"] = "高" if strong else ("低" if weak else "中")
    # Extract key sentence after "投资方案" or "执行摘要"
    summary_match = re.search(r"(?:投资方案|执行摘要|综合评估)[：:]\s*(.{10,200})", judge)
    if summary_match:
        consensus["summary"] = summary_match.group(1).strip()[:200]
    return consensus


def _confidence_to_numeric(consensus: dict) -> float:
    """将辩论共识的文字信心映射为 0.0–1.0 的数值。

    映射规则：
    - "高" → 0.9
    - "中" → 0.6
    - "低" → 0.3
    - 无数据 → 0.5（中性默认值）
    """
    conf_label = consensus.get("confidence", "")
    mapping = {"高": 0.9, "中": 0.6, "低": 0.3}
    return mapping.get(conf_label, 0.5)


def extract_key_assumptions(result: dict) -> list[str]:
    """从交易员计划和风控辩论中提取关键假设，供后续验证。"""
    assumptions = []
    trader_plan = result.get("trader_investment_plan", "")
    investment_plan = result.get("investment_plan", "")
    risk = result.get("risk_debate_state", {})
    risk_text = risk.get("judge_decision", "") if isinstance(risk, dict) else ""
    combined = "\n".join(filter(None, [trader_plan, investment_plan, risk_text]))
    if not combined:
        return []
    # Pattern 1: explicit assumption markers
    patterns = [
        r"假设[：:]\s*(.+?)(?:\n|$)",
        r"前提[：:]\s*(.+?)(?:\n|$)",
        r"预期[：:]\s*(.+?)(?:\n|$)",
        r"基于[：:]\s*(.+?)(?:\n|$)",
    ]
    for pat in patterns:
        matches = re.findall(pat, combined)
        for m in matches:
            clean = re.sub(r"\*{1,2}", "", m.strip())
            if len(clean) > 10:
                assumptions.append(clean[:150])
    # Pattern 2: conditional statements
    conditionals = re.findall(r"如果(.{10,80}?)(?:[，。,.])", combined)
    for c in conditionals[:3]:
        assumptions.append(f"假设: {c.strip()}")
    # Deduplicate
    seen = set()
    unique = []
    for a in assumptions:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return unique[:5]


def find_previous_analysis(
    stock_code: str, trade_date: str, snapshots: list[dict]
) -> dict | None:
    """查找同一标的最近一次历史分析（不含当前日期）。

    Returns:
        最近一次历史快照 dict，或 None（无历史记录时）。
    """
    prev = [
        s
        for s in snapshots
        if s.get("stock_code") == stock_code
        and s.get("analysis_date", "") < trade_date
    ]
    if not prev:
        return None
    # 按日期降序，取最近一次
    prev.sort(key=lambda s: s.get("analysis_date", ""), reverse=True)
    return prev[0]


_RATING_ORDER = {"买入": 5, "增持": 4, "持有": 3, "减持": 2, "卖出": 1}


def build_comparison(current: dict, prev: dict) -> dict:
    """构建本次分析与历史分析的对比字段。

    包含：上次日期/评级/得分、评级是否变化、价格变动幅度、方向一致性。
    """
    prev_date = prev.get("analysis_date", "")
    prev_rating = prev.get("rating", "")
    prev_price = prev.get("analysis_price")
    prev_score = prev.get("score")
    prev_verified = prev.get("verified", False)

    curr_rating = current.get("rating", "")
    curr_price = current.get("analysis_price")

    # 评级变化
    rating_changed = prev_rating != curr_rating
    rating_shift = 0
    if prev_rating in _RATING_ORDER and curr_rating in _RATING_ORDER:
        rating_shift = _RATING_ORDER[curr_rating] - _RATING_ORDER[prev_rating]

    # 价格变动
    price_change_pct = None
    if prev_price and curr_price and prev_price > 0:
        price_change_pct = round((curr_price - prev_price) / prev_price * 100, 2)

    # 上次预测是否正确（仅已验证的有意义）
    prev_correct = None
    if prev_verified and prev_score is not None:
        prev_correct = prev_score > 50  # 得分 > 50 视为方向正确

    comparison = {
        "prev_date": prev_date,
        "prev_rating": prev_rating,
        "prev_score": prev_score,
        "prev_verified": prev_verified,
        "prev_correct": prev_correct,
        "rating_changed": rating_changed,
        "rating_shift": rating_shift,  # 正=调升, 负=调降, 0=不变
        "price_change_pct": price_change_pct,
        "interval_days": _calc_interval_days(prev_date, current.get("analysis_date", "")),
    }
    return comparison


def _calc_interval_days(date_a: str, date_b: str) -> int | None:
    """计算两个 YYYY-MM-DD 日期之间的日历天数差。"""
    try:
        da = datetime.strptime(date_a, "%Y-%m-%d")
        db = datetime.strptime(date_b, "%Y-%m-%d")
        return (db - da).days
    except (ValueError, TypeError):
        return None


def save_snapshot(result_path: str) -> dict:
    """读取结果 JSON 并保存快照到 analysis_log.json。"""
    # 读取结果文件
    with open(result_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    stock_code = result.get("company_of_interest", "")
    trade_date = result.get("trade_date", "")
    rating = result.get("_rating", "")

    # 收集所有文本字段用于提取信息
    text_fields = [
        result.get("market_report", ""),
        result.get("sentiment_report", ""),
        result.get("news_report", ""),
        result.get("fundamentals_report", ""),
        result.get("final_trade_decision", ""),
    ]

    # 提取股票名称
    stock_name = extract_stock_name(stock_code, text_fields)

    # 提取股价（优先从交易决策中提取）
    price = None
    for field in [
        result.get("final_trade_decision", ""),
        result.get("trader_investment_plan", ""),
        result.get("fundamentals_report", ""),
        result.get("market_report", ""),
    ]:
        price = extract_price(field)
        if price:
            break

    # 提取辩论关键理由（优先从投资辩论，不足时补充风控要点）
    debate = result.get("investment_debate_state", {})
    judge_text = debate.get("judge_decision", "") if isinstance(debate, dict) else ""
    key_reasons = extract_key_reasons(judge_text)

    # 提取风控要点
    risk = result.get("risk_debate_state", {})
    risk_text = risk.get("judge_decision", "") if isinstance(risk, dict) else ""
    risk_points = extract_key_reasons(risk_text, max_reasons=3)

    # 如果辩论理由为空，用风控要点补充（风控辩论通常包含更完整的投资逻辑）
    if not key_reasons and risk_text:
        all_risk_reasons = extract_key_reasons(risk_text, max_reasons=5)
        key_reasons = all_risk_reasons

    # 提取辩论共识（供快照 confidence 字段和 debate_consensus 字段使用）
    debate_consensus = extract_debate_consensus(result)

    # 构建快照记录
    snapshot = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "analysis_date": trade_date,
        "analysis_price": price,
        "rating": rating,
        "key_reasons": key_reasons,
        "risk_points": risk_points,
        "elapsed_seconds": result.get("_elapsed_seconds", 0),
        "result_file": result_path,
        "snapshot_time": datetime.now().isoformat(timespec="seconds"),
        # v0.3 新增：分析师信号 / 辩论共识 / 关键假设
        "analyst_signals": extract_analyst_signals(result),
        "debate_consensus": debate_consensus,
        "confidence": _confidence_to_numeric(debate_consensus),
        "key_assumptions": extract_key_assumptions(result),
        # 回测跟踪字段（初始为空，由复盘 skill 填充）
        "track_t1": None,
        "track_t5": None,
        "track_t10": None,
        "track_t20": None,
        "verified": False,
    }

    # ── 同标的对比追踪 ──────────────────────────────────────
    log_data = {"version": 1, "snapshots": []}
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                log_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    prev = find_previous_analysis(stock_code, trade_date, log_data.get("snapshots", []))
    comparison_info = None
    if prev:
        comparison_info = build_comparison(snapshot, prev)
        snapshot["previous_analysis"] = comparison_info

    # 检查是否已存在同一股票同一日期的记录（去重）
    existing = [
        s
        for s in log_data.get("snapshots", [])
        if s["stock_code"] == stock_code and s["analysis_date"] == trade_date
    ]
    if existing:
        # 更新已有记录
        idx = log_data["snapshots"].index(existing[0])
        log_data["snapshots"][idx] = snapshot
        action = "updated"
    else:
        # 追加新记录
        log_data.setdefault("snapshots", []).append(snapshot)
        action = "appended"

    # 确保目录存在
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    # 写入
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    # 输出结果
    output = {
        "status": "ok",
        "action": action,
        "stock": f"{stock_code} {stock_name}",
        "date": trade_date,
        "rating": rating,
        "price": price,
        "reasons_count": len(key_reasons),
        "log_path": LOG_PATH,
        "total_snapshots": len(log_data.get("snapshots", [])),
    }
    if comparison_info:
        shift_map = {0: "不变", 1: "小幅调升", 2: "大幅调升", -1: "小幅调降", -2: "大幅调降"}
        shift_label = shift_map.get(comparison_info["rating_shift"], f"变动{comparison_info['rating_shift']}")
        price_str = f"{comparison_info['price_change_pct']:+.1f}%" if comparison_info["price_change_pct"] is not None else "N/A"
        prev_correct_str = (
            "正确" if comparison_info["prev_correct"] is True
            else ("错误" if comparison_info["prev_correct"] is False else "未验证")
        )
        output["comparison"] = (
            f"上次({comparison_info['prev_date']}): "
            f"{comparison_info['prev_rating']}→{rating} ({shift_label}), "
            f"价格{price_str}, "
            f"上次预测{prev_correct_str}"
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python save_snapshot.py <result_json_path>", file=sys.stderr)
        sys.exit(1)

    result_path = sys.argv[1]
    if not os.path.exists(result_path):
        print(f"Error: file not found: {result_path}", file=sys.stderr)
        sys.exit(1)

    save_snapshot(result_path)
