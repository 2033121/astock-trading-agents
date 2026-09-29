"""Rating parser — 从 LLM 文本输出中提取投资评级。

支持中文评级（买入/增持/持有/减持/卖出）和英文评级（Buy/Overweight/Hold/Underweight/Sell）。
采用两轮匹配策略：

1. 第一轮：查找 ``评级: X`` / ``**评级**: X`` 标签模式
2. 第二轮：在全文中搜索评级关键词（先剥掉「五级刻度」枚举）

**刻度之外的输出不会被硬塞进五档。** :func:`extract_rating` 在解析不出评级时
返回 ``None``，由调用方决定怎么处理（信号处理器给出 :data:`RATING_REVIEW`
「待复核」）。把一个解析失败的决策静默当成「持有」是危险的：它看起来像一个
真实的中性判断，实际只是解析失败，会污染记忆、报告和事后复盘（上游
`TradingAgents <https://github.com/TauricResearch/TradingAgents>`_ #1170 同类修复）。

:func:`parse_rating` 保留旧的「无论如何都给一个评级」语义，供确实需要字符串的
历史调用点使用。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 中文评级关键词（优先级从高到低）
_CN_RATINGS = ["买入", "增持", "持有", "减持", "卖出"]

# 对外发布的规范化元组，避免调用方各自复制刻度
RATINGS: tuple[str, ...] = tuple(_CN_RATINGS)

# 解析不出评级时对外释放的信号。它不是可交易仓位，而是「需要人工/重跑」的标记。
RATING_REVIEW = "待复核"

# 英文 → 中文映射（不区分大小写匹配时使用小写键）
_EN_TO_CN: dict[str, str] = {
    "buy": "买入",
    "overweight": "增持",
    "hold": "持有",
    "underweight": "减持",
    "sell": "卖出",
}

# 英文关键词按「词干 + 常见变形」匹配，避免 ``buyer`` / ``seller`` / ``buyback``
# 这类同根词被误判成评级；同时仍然覆盖 buying / sells / holding 等自然写法。
_EN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bbuy(?:s|ing)?\b", re.IGNORECASE), "买入"),
    (re.compile(r"\boverweight\b", re.IGNORECASE), "增持"),
    (re.compile(r"\bhold(?:s|ing)?\b", re.IGNORECASE), "持有"),
    (re.compile(r"\bunderweight\b", re.IGNORECASE), "减持"),
    (re.compile(r"\bsell(?:s|ing)?\b|\bsold\b", re.IGNORECASE), "卖出"),
]

# 预编译正则 — 标签模式:  **评级**: 买入  或  评级: 买入  或  Rating: Buy
_LABEL_PATTERN = re.compile(
    r"(?:\*{0,2})评级(?:\*{0,2})\s*[:：]\s*([^\s\n*]+)",
    re.IGNORECASE,
)
_LABEL_PATTERN_EN = re.compile(
    r"(?:\*{0,2})rating(?:\*{0,2})\s*[:：]\s*([^\s\n*]+)",
    re.IGNORECASE,
)

# 「五级刻度」枚举：连续列出 3 个及以上刻度词，中间由分隔符连接。
# 例如「买入/增持/持有/减持/卖出」。它描述的是量表本身，不是结论。
_SCALE_RUN_CN = re.compile(
    r"(?:买入|增持|持有|减持|卖出)"
    r"(?:\s*[、,，/|｜和或]\s*(?:买入|增持|持有|减持|卖出)){2,}"
)
_SCALE_RUN_EN = re.compile(
    r"\b(?:Buy|Overweight|Hold|Underweight|Sell)\b"
    r"(?:\s*[、,，/|｜和或]?\s*\b(?:Buy|Overweight|Hold|Underweight|Sell)\b){2,}",
    re.IGNORECASE,
)

# 一行里出现这么多个不同刻度词，就认为它在描述量表而不是表态
_SCALE_LINE_THRESHOLD = 3


def extract_rating(text: str | None) -> str | None:
    """从文本中提取投资评级；解析不出时返回 ``None``。

    Parameters
    ----------
    text : str | None
        LLM 输出的 Markdown / 纯文本。

    Returns
    -------
    str | None
        ``"买入"`` / ``"增持"`` / ``"持有"`` / ``"减持"`` / ``"卖出"``；
        无法确定时返回 ``None``（**不猜、不兜底**）。

    Notes
    -----
    标签模式命中了但值不在五级刻度内（例如 ``评级: 观望``）会直接返回 ``None``，
    不再退回全文搜索：那种情况下唯一能被搜到的往往是「买入/增持/持有/减持/卖出」
    这类刻度说明，捞出来的评级是凭空造的。
    """
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None

    # ── 第一轮：标签模式匹配 ────────────────────────────────
    for pattern in (_LABEL_PATTERN, _LABEL_PATTERN_EN):
        m = pattern.search(stripped)
        if m:
            result = _resolve_keyword(m.group(1).strip())
            if result:
                return result
            logger.debug("评级标签命中但取值 %r 不在五级刻度内，判定为无法解析。", m.group(1))
            return None

    # ── 第二轮：全文关键词搜索（按刻度优先级） ──────────────
    body = _strip_rating_scale(stripped)
    for kw in _CN_RATINGS:
        if kw in body:
            return kw
    for pattern, cn_kw in _EN_PATTERNS:
        if pattern.search(body):
            return cn_kw

    return None


def parse_rating(text: str | None, default: str = "持有") -> str:
    """从文本中提取投资评级，解析不出时回退到 *default*。

    兼容包装：**总是**返回一个评级字符串，所以无法解析的决策会静默变成
    *default*（默认「持有」）。需要区分「模型没说」和「模型说持有」的调用点
    应当改用 :func:`extract_rating`。

    Parameters
    ----------
    text : str | None
        LLM 输出的 Markdown / 纯文本。
    default : str
        无法匹配时的默认评级，默认 ``"持有"``。

    Returns
    -------
    str
        中文评级字符串：买入 / 增持 / 持有 / 减持 / 卖出。
    """
    rating = extract_rating(text)
    return rating if rating is not None else default


def _strip_rating_scale(text: str) -> str:
    """剥掉「五级刻度」的枚举，只留下表态性文本。

    决策文本里常见「评级（买入/增持/持有/减持/卖出）」这类刻度说明。留着它会让
    全文搜索永远命中刻度词表里的第一个「买入」，于是每篇报告都变成买入。这里做
    两层清理：

    1. 删掉连续的刻度枚举片段（保留同一行里的其他内容）
    2. 再把仍然列了 3 个以上不同刻度词的整行丢掉
    """
    stripped = _SCALE_RUN_CN.sub(" ", text)
    stripped = _SCALE_RUN_EN.sub(" ", stripped)
    kept = [line for line in stripped.splitlines() if _distinct_rating_count(line) < _SCALE_LINE_THRESHOLD]
    return "\n".join(kept)


def _distinct_rating_count(line: str) -> int:
    """一行里出现了多少个**不同**的中文刻度词。"""
    return sum(1 for kw in _CN_RATINGS if kw in line)


def _resolve_keyword(value: str) -> str | None:
    """尝试将单个关键词解析为中文评级。"""
    # 中文直接匹配
    if value in _CN_RATINGS:
        return value
    # 英文映射
    return _EN_TO_CN.get(value.lower())
