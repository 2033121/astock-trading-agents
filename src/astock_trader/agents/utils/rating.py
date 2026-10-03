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

    # ── 第二轮：全文关键词搜索（按**出现顺序**，跳过否定语境）──
    body = _strip_rating_scale(stripped)
    return _first_unnegated_stance(body)


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


# ---------------------------------------------------------------------------
# 交易动作提取
# ---------------------------------------------------------------------------
# 「操作」与「评级」是两个字段：评级来自基金经理，操作来自交易员的执行计划。
# 两者共用同一套五档刻度，也共用同一类误读风险 —— **否定句里的刻度词**。
#
# 旧实现是 ``for action in ("买入", "增持", ...): if action in plan``，有两个毛病：
#
# 1. **顺序偏见**：按刻度表顺序扫而不是按文中出现顺序，于是「不是买入信号，
#    以持有为主」永远返回「买入」；
# 2. **不认否定**：交易员写「这不是"买入信号"，而是布局框架」，字面上确实
#    出现了「买入」，但结论刚好相反。
#
# 现在改成：按出现位置排序 → 剔除处在否定语境的提及 → 取最靠前的一个。
# 一个都不剩时返回 ``None``，由调用方给出「未知」，**不猜**。

# 只收多字否定词。单字「非 / 未 / 无 / 不」在「未来」「非银」「不但」里会误伤，
# 宁可有漏网之鱼，也不要制造假否定。
_NEGATION_MARKERS = (
    "而不是",
    "而非",
    "不是",
    "并非",
    "不构成",
    "称不上",
    "谈不上",
    "不算",
    "不建议",
    "不宜",
    "不给予",
    "不支持",
    "避免",
    "没有",
)

# 只在刻度词**前面**这么多个字符里找否定词：「不构成买入」命中，
# 而「买入后不再卖出」这种前置否定落在远处的不会被误判。
_NEGATION_WINDOW = 12

# 小句边界。否定不跨句生效：「不建议买入，建议减持」里的「减持」不能被前一句的
# 「不建议」牵连。注意**不能**把引号算作边界 —— 「这不是"买入信号"」正是要靠
# 引号内侧的「不是」来判定的。
_CLAUSE_BOUNDARY = "，。；！？,.;!?：:\n\t（）()"


def _is_negated(text: str, pos: int) -> bool:
    """判断 ``pos`` 处的刻度词是否处在前置否定语境里。

    只在**当前小句**内判断：先把窗口退到最近一个句读，再在剩下的片段里找否定词。
    """
    window = text[max(0, pos - _NEGATION_WINDOW) : pos]
    cut = max((window.rfind(ch) for ch in _CLAUSE_BOUNDARY), default=-1)
    clause = window[cut + 1 :]
    return any(marker in clause for marker in _NEGATION_MARKERS)


def _stance_occurrences(body: str) -> list[tuple[int, str]]:
    """收集文中所有刻度词的出现位置（中英混排），按出现顺序排序。"""
    occurrences: list[tuple[int, str]] = []
    for kw in _CN_RATINGS:
        start = 0
        while (idx := body.find(kw, start)) != -1:
            occurrences.append((idx, kw))
            start = idx + len(kw)
    for pattern, cn_kw in _EN_PATTERNS:
        occurrences.extend((m.start(), cn_kw) for m in pattern.finditer(body))
    occurrences.sort()
    return occurrences


def _first_unnegated_stance(body: str) -> str | None:
    """取**最先出现**且不在否定语境里的刻度词；一个都不剩时返回 ``None``。

    两条规则缺一不可：

    * **按出现顺序**而非刻度表顺序 —— 否则「不是买入信号，以持有为主」永远返回
      「买入」，因为尺度表里「买入」排第一；
    * **跳过否定语境** —— 否则「低估值不是买入充分条件」会被读成买入评级。这条
      在实盘里真的发生过：基金经理白纸黑字写「最终评级：持有（HOLD）」，而解析
      出来的是「买入」，因为正文里有一句「低估值不是买入充分条件」。
    """
    for pos, kw in _stance_occurrences(body):
        if not _is_negated(body, pos):
            return kw
    return None


def extract_action(text: str | None) -> str | None:
    """从交易计划里提取操作方向；解析不出、或被否定时返回 ``None``。

    与 :func:`extract_rating` 共用同一套「按位置 + 跳过否定」的判据，区别只在
    输入字段：这里读的是交易员的 ``trader_investment_plan``。

    Parameters
    ----------
    text : str | None
        ``trader_investment_plan`` 的原文。

    Returns
    -------
    str | None
        五档刻度之一；无法确定时 ``None``（**不猜**）。
    """
    if not text or not text.strip():
        return None

    # 先剥掉「买入/增持/持有/减持/卖出」这类刻度枚举 —— 它描述量表，不是表态。
    body = _strip_rating_scale(text)
    stance = _first_unnegated_stance(body)
    if stance is None:
        logger.debug("交易计划里 %d 处刻度词全部处于否定语境，判定为无法解析。", len(_stance_occurrences(body)))
    return stance
