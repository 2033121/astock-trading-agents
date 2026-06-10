"""Rating parser — 从 LLM 文本输出中提取投资评级。

支持中文评级（买入/增持/持有/减持/卖出）和英文评级（Buy/Overweight/Hold/Underweight/Sell）。
采用两轮匹配策略：
  1. 第一轮：查找 ``评级: X`` 或 ``**评级**: X`` 标签模式
  2. 第二轮：在全文中搜索评级关键词
"""

from __future__ import annotations

import re

# 中文评级关键词（优先级从高到低）
_CN_RATINGS = ["买入", "增持", "持有", "减持", "卖出"]

# 英文 → 中文映射（不区分大小写匹配时使用小写键）
_EN_TO_CN: dict[str, str] = {
    "buy": "买入",
    "overweight": "增持",
    "hold": "持有",
    "underweight": "减持",
    "sell": "卖出",
}

# 预编译正则 — 标签模式:  **评级**: 买入  或  评级: 买入  或  Rating: Buy
_LABEL_PATTERN = re.compile(
    r"(?:\*{0,2})评级(?:\*{0,2})\s*[:：]\s*([^\s\n*]+)",
    re.IGNORECASE,
)
_LABEL_PATTERN_EN = re.compile(
    r"(?:\*{0,2})rating(?:\*{0,2})\s*[:：]\s*([^\s\n*]+)",
    re.IGNORECASE,
)


def parse_rating(text: str, default: str = "持有") -> str:
    """从文本中提取投资评级。

    Parameters
    ----------
    text : str
        LLM 输出的 Markdown / 纯文本。
    default : str
        无法匹配时的默认评级，默认 ``"持有"``。

    Returns
    -------
    str
        中文评级字符串：买入 / 增持 / 持有 / 减持 / 卖出。
    """
    if not text:
        return default

    # ── 第一轮：标签模式匹配 ────────────────────────────────
    for pattern in (_LABEL_PATTERN, _LABEL_PATTERN_EN):
        m = pattern.search(text)
        if m:
            value = m.group(1).strip()
            result = _resolve_keyword(value)
            if result:
                return result

    # ── 第二轮：全文关键词搜索 ──────────────────────────────
    # 中文关键词
    for kw in _CN_RATINGS:
        if kw in text:
            return kw

    # 英文关键词（不区分大小写）
    text_lower = text.lower()
    for en_kw, cn_kw in _EN_TO_CN.items():
        if en_kw in text_lower:
            return cn_kw

    return default


def _resolve_keyword(value: str) -> str | None:
    """尝试将单个关键词解析为中文评级。"""
    # 中文直接匹配
    if value in _CN_RATINGS:
        return value
    # 英文映射
    cn = _EN_TO_CN.get(value.lower())
    return cn
