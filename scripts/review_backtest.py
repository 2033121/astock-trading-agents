#!/usr/bin/env python3
"""
分析复盘回测工具
读取 analysis_log.json 中的分析快照，获取后续实际股价，计算准确率。

用法:
    python3 review_backtest.py [--days N] [--report]

参数:
    --days N    只回测分析日期距今 >= N 天的记录（默认 0，即全部）
    --report    输出人类可读的复盘报告（默认输出 JSON）
"""

import json
import sys
import os
from datetime import datetime, timedelta

LOG_PATH = r"D:\stock\trading-agents\analysis_log.json"
REPORT_PATH = r"D:\stock\trading-agents\latest_report.md"

# 评级映射：正值表示看多，负值表示看空
RATING_DIRECTION = {
    "买入": 2,    # 强烈看多
    "增持": 1,    # 偏看多
    "持有": 0,    # 中性
    "减持": -1,   # 偏看空
    "卖出": -2,   # 强烈看空
}


def fetch_price_akshare(stock_code: str, start_date: str, end_date: str) -> dict:
    """
    用 akshare 获取指定股票在日期范围内的日线数据。
    返回 {date_str: close_price} 字典。
    """
    try:
        import akshare as ak
    except ImportError:
        print("Error: akshare not installed. Run: pip install akshare", file=sys.stderr)
        return {}

    try:
        # akshare 的 A 股日线接口
        symbol = stock_code.zfill(6)
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="qfq",  # 前复权
        )
        if df is None or df.empty:
            return {}

        prices = {}
        for _, row in df.iterrows():
            date_str = str(row["日期"])
            close = float(row["收盘"])
            prices[date_str] = close
        return prices
    except Exception as e:
        print(f"Warning: akshare fetch failed for {stock_code}: {e}", file=sys.stderr)
        return {}


def find_trading_day(prices: dict, target_date: str, direction: str = "forward") -> str | None:
    """
    在价格字典中找到最接近目标日期的交易日。
    direction: 'forward' 向后找最近的交易日, 'backward' 向前找
    """
    target = datetime.strptime(target_date, "%Y-%m-%d")
    sorted_dates = sorted(prices.keys())

    if not sorted_dates:
        return None

    if direction == "forward":
        for d in sorted_dates:
            if d >= target_date:
                return d
        return sorted_dates[-1]  # 如果都没有，返回最后一个
    else:
        for d in reversed(sorted_dates):
            if d <= target_date:
                return d
        return sorted_dates[0]


def calculate_tracking(snapshot: dict, prices: dict) -> dict:
    """
    计算某个快照在 T+1/T+5/T+10/T+20 的价格变化。

    T+N 表示 N 个**交易日**后的价格（而非日历日），通过 prices 中
    实际存在的交易日列表来定位，避免跨周末/节假日导致的间隔偏差。
    """
    analysis_date = snapshot["analysis_date"]
    analysis_price = snapshot.get("analysis_price")
    rating = snapshot.get("rating", "持有")

    if not analysis_price or not prices:
        return snapshot

    result = dict(snapshot)  # 浅拷贝

    # 按日期排序获取交易日列表（仅保留分析日期之后的）
    all_trading_days = sorted(
        d for d in prices.keys() if d > analysis_date
    )

    tracking_periods = [
        ("track_t1", 1),
        ("track_t5", 5),
        ("track_t10", 10),
        ("track_t20", 20),
    ]

    for field, trading_days_offset in tracking_periods:
        # 取第 N 个交易日（索引 N-1，因为 T+1 = 分析后第1个交易日 = index 0）
        idx = trading_days_offset - 1
        if idx < len(all_trading_days):
            trade_day = all_trading_days[idx]
            actual_price = prices[trade_day]
            change_pct = round((actual_price - analysis_price) / analysis_price * 100, 2)

            # 判断评级是否正确
            direction = RATING_DIRECTION.get(rating, 0)
            if direction > 0:
                correct = change_pct > 0  # 看多时涨了就对
            elif direction < 0:
                correct = change_pct < 0  # 看空时跌了就对
            else:
                correct = abs(change_pct) < 3  # 持有时波动小就对

            result[field] = {
                "date": trade_day,
                "price": actual_price,
                "change_pct": change_pct,
                "correct": correct,
            }

    # 标记已验证（至少有一个 T 期数据）
    if any(result.get(f) for f, _ in tracking_periods):
        result["verified"] = True

    return result


def score_snapshot(snapshot: dict) -> dict:
    """
    Multi-dimensional scoring for a single snapshot.

    Dimensions:
    - Direction accuracy (40%): Was the price movement direction correct?
    - Magnitude alignment (25%): How close was predicted magnitude to actual?
    - Timing quality (15%): Did the move happen within the expected timeframe?
    - Assumption validation (20%): Were key assumptions validated or invalidated?
    """
    rating = snapshot.get("rating", "持有")
    direction_value = RATING_DIRECTION.get(rating, 0)
    tracks = []
    for field in ["track_t1", "track_t5", "track_t10", "track_t20"]:
        t = snapshot.get(field)
        if t and isinstance(t, dict):
            tracks.append(t)

    if not tracks:
        return {"score": None, "detail": "尚无跟踪数据", "dimensions": {}}

    # Weights per period: T+1=0.10, T+5=0.20, T+10=0.35, T+20=0.35
    period_weights = [0.10, 0.20, 0.35, 0.35]

    # ── Dimension 1: Direction accuracy (0-100) ──
    dir_scores = []
    for i, t in enumerate(tracks):
        change = t.get("change_pct", 0)
        if direction_value > 0 and change > 0:
            dir_scores.append(100)
        elif direction_value < 0 and change < 0:
            dir_scores.append(100)
        elif direction_value == 0 and abs(change) < 3:
            dir_scores.append(100)
        elif direction_value == 0:
            dir_scores.append(max(0, 100 - abs(change) * 10))
        else:
            # Wrong direction — partial credit for small moves
            dir_scores.append(max(0, 50 - abs(change) * 5))
    w_dir = sum(s * period_weights[i] for i, s in enumerate(dir_scores))

    # ── Dimension 2: Magnitude alignment (0-100) ──
    mag_scores = []
    for t in tracks:
        change = abs(t.get("change_pct", 0))
        # Strong buy/sell expect >5%, moderate expect 2-5%, hold expect <3%
        if abs(direction_value) >= 2:
            expected = 5.0
        elif abs(direction_value) == 1:
            expected = 3.0
        else:
            expected = 1.5
        deviation = abs(change - expected)
        mag_scores.append(max(0, 100 - deviation * 15))
    w_mag = sum(s * period_weights[i] for i, s in enumerate(mag_scores))

    # ── Dimension 3: Timing quality (0-100) ──
    # Earlier confirmation = higher score
    timing_scores = []
    for i, t in enumerate(tracks):
        change = t.get("change_pct", 0)
        direction_correct = (
            (direction_value > 0 and change > 0)
            or (direction_value < 0 and change < 0)
            or (direction_value == 0 and abs(change) < 3)
        )
        if direction_correct:
            # Earlier periods score higher
            timing_scores.append(100 - i * 15)
        else:
            timing_scores.append(0)
    w_timing = sum(s * period_weights[i] for i, s in enumerate(timing_scores))

    # ── Dimension 4: Assumption validation (0-100) ──
    assumptions = snapshot.get("key_assumptions", [])
    if assumptions and len(tracks) >= 2:
        # Simple heuristic: if direction was correct at T+10 and T+20, assumptions likely held
        late_correct = sum(
            1 for i in range(2, len(tracks))
            if (direction_value > 0 and tracks[i].get("change_pct", 0) > 0)
            or (direction_value < 0 and tracks[i].get("change_pct", 0) < 0)
        )
        w_assumption = min(100, late_correct / max(1, len(tracks) - 2) * 100)
    else:
        w_assumption = 50  # neutral when no assumptions to validate

    # ── Composite score ──
    dim_weights = {"direction": 0.40, "magnitude": 0.25, "timing": 0.15, "assumption": 0.20}
    composite = round(
        w_dir * dim_weights["direction"]
        + w_mag * dim_weights["magnitude"]
        + w_timing * dim_weights["timing"]
        + w_assumption * dim_weights["assumption"],
        1,
    )

    changes = [f"{t.get('change_pct', 0):+.1f}%" for t in tracks]
    dimensions = {
        "direction": round(w_dir, 1),
        "magnitude": round(w_mag, 1),
        "timing": round(w_timing, 1),
        "assumption": round(w_assumption, 1),
    }

    return {
        "score": composite,
        "changes": changes,
        "detail": " → ".join(changes),
        "dimensions": dimensions,
    }


def recognize_patterns(snapshots: list[dict]) -> dict:
    """
    Identify systematic biases across verified snapshots.

    Returns a dict with:
    - rating_bias: Which ratings tend to be over/under-confident
    - magnitude_bias: Systematic over/under-estimation of move size
    - industry_weakness: If industry data is available, which sectors underperform
    """
    patterns = {"rating_bias": {}, "magnitude_bias": {}, "insights": []}
    verified = [s for s in snapshots if s.get("verified") and s.get("score") is not None]

    if len(verified) < 3:
        return patterns

    # ── Rating bias ──
    from collections import defaultdict
    rating_scores = defaultdict(list)
    for s in verified:
        rating = s.get("rating", "持有")
        rating_scores[rating].append(s["score"])

    for rating, scores in rating_scores.items():
        avg = sum(scores) / len(scores)
        patterns["rating_bias"][rating] = {
            "count": len(scores),
            "avg_score": round(avg, 1),
            "assessment": "准确" if avg >= 60 else ("偏差" if avg < 40 else "一般"),
        }

    # ── Magnitude bias ──
    over_estimated = 0
    under_estimated = 0
    for s in verified:
        dims = s.get("dimensions", {}) if isinstance(s.get("dimensions"), dict) else {}
        # Check score_detail for old format compat
        if not dims and "dimensions" in s:
            dims = s["dimensions"]
        mag_score = dims.get("magnitude", 50)
        if mag_score < 30:
            over_estimated += 1
        elif mag_score > 70:
            under_estimated += 1

    if over_estimated > under_estimated and over_estimated > len(verified) * 0.3:
        patterns["magnitude_bias"] = {"type": "高估倾向", "count": over_estimated}
        patterns["insights"].append("系统倾向于高估价格变动幅度，建议降低目标价预期。")
    elif under_estimated > over_estimated and under_estimated > len(verified) * 0.3:
        patterns["magnitude_bias"] = {"type": "低估倾向", "count": under_estimated}
        patterns["insights"].append("系统倾向于低估价格变动幅度，可适当提高目标价预期。")

    # ── Direction bias ──
    bullish_count = sum(1 for s in verified if RATING_DIRECTION.get(s.get("rating", ""), 0) > 0)
    bearish_count = sum(1 for s in verified if RATING_DIRECTION.get(s.get("rating", ""), 0) < 0)
    total = len(verified)
    if bullish_count > total * 0.7:
        patterns["insights"].append(f"评级偏多头：{bullish_count}/{total} 为看多评级，可能存在系统性乐观偏差。")
    elif bearish_count > total * 0.7:
        patterns["insights"].append(f"评级偏空头：{bearish_count}/{total} 为看空评级，可能存在系统性悲观偏差。")

    return patterns


def generate_strategy_feedback(snapshots: list[dict], patterns: dict) -> str:
    """
    Generate actionable feedback text that can be injected into analyst prompts
    for future analyses.

    Returns a concise feedback string (suitable for prompt injection).
    """
    feedback_parts = []

    # From pattern insights
    insights = patterns.get("insights", [])
    for insight in insights[:3]:
        feedback_parts.append(insight)

    # From rating bias
    rating_bias = patterns.get("rating_bias", {})
    weak_ratings = [r for r, info in rating_bias.items() if info.get("avg_score", 50) < 40]
    if weak_ratings:
        feedback_parts.append(f"注意：{'/'.join(weak_ratings)} 评级历史准确率偏低，给出此类评级时需更充分的论据支撑。")

    # From individual low-scoring snapshots
    verified = [s for s in snapshots if s.get("verified") and s.get("score") is not None]
    low_scores = [s for s in verified if s["score"] < 30]
    if low_scores:
        names = [f"{s['stock_name']}({s['analysis_date']})" for s in low_scores[:3]]
        feedback_parts.append(f"历史重大偏差案例：{', '.join(names)}，请复盘这些案例的教训。")

    if not feedback_parts:
        return ""

    return "## 历史策略反馈（基于回测数据）\n" + "\n".join(f"- {p}" for p in feedback_parts)


def run_backtest(days_threshold: int = 0) -> tuple[list[dict], dict]:
    """
    运行回测，返回更新后的快照列表和统计摘要。
    """
    # 读取日志
    if not os.path.exists(LOG_PATH):
        print(f"Error: {LOG_PATH} not found", file=sys.stderr)
        sys.exit(1)

    with open(LOG_PATH, "r", encoding="utf-8") as f:
        log_data = json.load(f)

    snapshots = log_data.get("snapshots", [])
    today = datetime.now()
    updated = []
    stats = {"total": 0, "verified": 0, "scores": [], "correct_ratings": [], "wrong_ratings": []}

    for snap in snapshots:
        analysis_date = snap.get("analysis_date", "")
        days_since = (today - datetime.strptime(analysis_date, "%Y-%m-%d")).days

        # 跳过太新的记录
        if days_since < max(1, days_threshold):
            updated.append(snap)
            continue

        stats["total"] += 1
        stock_code = snap.get("stock_code", "")

        # 获取从分析日期起足够覆盖 T+20 交易日的价格数据
        # T+20 交易日 ≈ 28 日历日，加 buffer 到 45 天确保覆盖节假日
        end_date = (datetime.strptime(analysis_date, "%Y-%m-%d") + timedelta(days=45)).strftime("%Y-%m-%d")
        if datetime.strptime(end_date, "%Y-%m-%d") > today:
            end_date = today.strftime("%Y-%m-%d")

        prices = fetch_price_akshare(stock_code, analysis_date, end_date)

        if prices:
            snap = calculate_tracking(snap, prices)

        # 计算评分
        score_info = score_snapshot(snap)
        snap["score"] = score_info.get("score")
        snap["score_detail"] = score_info.get("detail", "")
        snap["dimensions"] = score_info.get("dimensions", {})

        if snap.get("verified"):
            stats["verified"] += 1
            if score_info.get("score") is not None:
                stats["scores"].append(score_info["score"])

                # 分类统计
                rating = snap.get("rating", "持有")
                if score_info["score"] >= 50:
                    stats["correct_ratings"].append(f"{snap['stock_name']}({rating})")
                else:
                    stats["wrong_ratings"].append(f"{snap['stock_name']}({rating})")

        updated.append(snap)

    # 模式识别
    patterns = recognize_patterns(updated)
    strategy_feedback = generate_strategy_feedback(updated, patterns)

    # 汇总统计
    summary = {
        "total_snapshots": stats["total"],
        "verified_count": stats["verified"],
        "avg_score": round(sum(stats["scores"]) / len(stats["scores"]), 1) if stats["scores"] else None,
        "max_score": max(stats["scores"]) if stats["scores"] else None,
        "min_score": min(stats["scores"]) if stats["scores"] else None,
        "correct_predictions": stats["correct_ratings"],
        "wrong_predictions": stats["wrong_ratings"],
        "backtest_time": today.isoformat(timespec="seconds"),
        "patterns": patterns,
        "strategy_feedback": strategy_feedback,
    }

    return updated, summary


def save_updated_log(snapshots: list[dict]):
    """保存更新后的快照到日志文件。"""
    log_data = {"version": 1, "snapshots": snapshots}
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)


def generate_report(snapshots: list[dict], summary: dict) -> str:
    """生成人类可读的 Markdown 复盘报告。"""
    lines = []
    lines.append(f"## 分析复盘报告")
    lines.append(f"生成时间：{summary['backtest_time']}")
    lines.append("")

    # 汇总
    lines.append("### 整体表现")
    lines.append(f"- 分析记录总数：{summary['total_snapshots']}")
    lines.append(f"- 已验证记录：{summary['verified_count']}")
    if summary["avg_score"] is not None:
        lines.append(f"- 平均准确率：**{summary['avg_score']}%**")
        lines.append(f"- 最高分：{summary['max_score']}%")
        lines.append(f"- 最低分：{summary['min_score']}%")
    else:
        lines.append("- 平均准确率：暂无（无足够跟踪数据）")
    lines.append("")

    # 正确/错误预测
    if summary["correct_predictions"]:
        lines.append(f"**预测正确**：{', '.join(summary['correct_predictions'])}")
    if summary["wrong_predictions"]:
        lines.append(f"**预测偏差**：{', '.join(summary['wrong_predictions'])}")
    lines.append("")

    # 逐条详情
    lines.append("### 逐条详情")
    lines.append("")

    for snap in snapshots:
        if not snap.get("verified"):
            continue

        stock = f"{snap['stock_code']} {snap['stock_name']}"
        date = snap["analysis_date"]
        rating = snap.get("rating", "—")
        price = snap.get("analysis_price", "—")
        score = snap.get("score", "—")
        detail = snap.get("score_detail", "")

        # 评级 emoji
        emoji = {"买入": "🟢", "增持": "🔵", "持有": "⚪", "减持": "🟡", "卖出": "🔴"}.get(rating, "⚫")

        lines.append(f"**{stock}** | {date} | {emoji} {rating} | 分析价 {price} | 得分 {score}%")
        if detail:
            lines.append(f"  变化轨迹：{detail}")

        # 各期数据
        for field, label in [("track_t1", "T+1"), ("track_t5", "T+5"), ("track_t10", "T+10"), ("track_t20", "T+20")]:
            t = snap.get(field)
            if t and isinstance(t, dict):
                mark = "✅" if t.get("correct") else "❌"
                lines.append(f"  - {label}({t['date']})：{t['price']:.2f}元 {t['change_pct']:+.1f}% {mark}")

        # 关键理由回顾
        if snap.get("key_reasons"):
            lines.append("  理由回顾：")
            for r in snap["key_reasons"][:3]:
                lines.append(f"    - {r[:80]}...")

        # 多维评分
        dims = snap.get("dimensions", {})
        if isinstance(dims, dict) and dims:
            dim_str = " | ".join(f"{k}={v}分" for k, v in dims.items())
            lines.append(f"  多维评分：{dim_str}")

        # 假设验证
        assumptions = snap.get("key_assumptions", [])
        if assumptions:
            lines.append("  关键假设：")
            for a in assumptions[:3]:
                lines.append(f"    - {a[:80]}")

        lines.append("")

    # 模式识别
    patterns = summary.get("patterns", {})
    if patterns and patterns.get("insights"):
        lines.append("### 模式识别")
        lines.append("")
        for insight in patterns["insights"]:
            lines.append(f"- {insight}")
        # Rating bias details
        rating_bias = patterns.get("rating_bias", {})
        if rating_bias:
            lines.append("")
            lines.append("**评级准确率**：")
            for rating, info in rating_bias.items():
                lines.append(f"- {rating}: {info['count']}次, 平均{info['avg_score']}分 ({info['assessment']})")
        lines.append("")

    # 策略反馈
    feedback = summary.get("strategy_feedback", "")
    if feedback:
        lines.append("### 策略改进建议")
        lines.append("")
        lines.append(feedback)
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="分析复盘回测工具")
    parser.add_argument("--days", type=int, default=0, help="只回测分析日期距今 >= N 天的记录")
    parser.add_argument("--report", action="store_true", help="生成 Markdown 报告")
    args = parser.parse_args()

    snapshots, summary = run_backtest(args.days)
    save_updated_log(snapshots)

    if args.report:
        report = generate_report(snapshots, summary)
        # 保存报告
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report saved to: {REPORT_PATH}")
        print(report)
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
