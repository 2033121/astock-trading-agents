"""Agent state definitions — 兼容 TradingAgents 状态模式。

所有 LangGraph 节点通过 ``AgentState`` 传递数据。
子状态 ``InvestDebateState`` 和 ``RiskDebateState`` 使用普通 TypedDict，
嵌套在 ``AgentState`` 中作为字段。
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import MessagesState

# ────────────────────────────────────────────────────────────
#  Reducer helpers
# ────────────────────────────────────────────────────────────


def _append_str_list(left: list[str] | None, right: list[str] | None) -> list[str]:
    """追加字符串列表，兼容 None 初始值。"""
    left = left or []
    right = right or []
    return left + right


# ────────────────────────────────────────────────────────────
#  Invest Debate State — 多空辩论子状态
# ────────────────────────────────────────────────────────────


class InvestDebateState(TypedDict, total=False):
    """多头 vs 空头辩论的完整状态。"""

    bull_history: Annotated[list[str], _append_str_list]
    """多头分析师的发言历史（自动追加）"""

    bear_history: Annotated[list[str], _append_str_list]
    """空头分析师的发言历史（自动追加）"""

    history: Annotated[list[str], _append_str_list]
    """辩论全程消息历史"""

    current_response: str
    """当前轮次的最新回复"""

    judge_decision: str | None
    """裁判（研究员）的最终裁决"""

    count: int
    """已辩论轮数"""


# ────────────────────────────────────────────────────────────
#  Risk Debate State — 风控辩论子状态
# ────────────────────────────────────────────────────────────


class RiskDebateState(TypedDict, total=False):
    """激进 / 保守 / 中性三方风控辩论状态。"""

    aggressive_history: Annotated[list[str], _append_str_list]
    """激进派风控发言历史"""

    conservative_history: Annotated[list[str], _append_str_list]
    """保守派风控发言历史"""

    neutral_history: Annotated[list[str], _append_str_list]
    """中性派风控发言历史"""

    history: Annotated[list[str], _append_str_list]
    """风控辩论全程消息历史"""

    latest_speaker: str | None
    """最近发言角色标识"""

    current_aggressive_response: str
    """激进派当前回复"""

    current_conservative_response: str
    """保守派当前回复"""

    current_neutral_response: str
    """中性派当前回复"""

    judge_decision: str | None
    """风控裁判最终裁决"""

    count: int
    """已辩论轮数"""


# ────────────────────────────────────────────────────────────
#  Agent State — LangGraph 主状态
# ────────────────────────────────────────────────────────────


class AgentState(MessagesState):
    """LangGraph 全局状态，所有节点共享此结构。

    继承 ``MessagesState`` 以获得 ``messages`` 字段（自带 ``add_messages`` reducer）。
    """

    # ── 基本上下文 ─────────────────────────────────────────
    company_of_interest: str
    """目标公司名称 / 股票代码"""

    trade_date: str
    """交易日期，格式 YYYY-MM-DD"""

    sender: str | None
    """当前发言的 Agent 名称"""

    # ── 各维度分析报告 ──────────────────────────────────────
    market_report: str
    """市场 / 技术面分析报告"""

    sentiment_report: str
    """市场情绪分析报告"""

    news_report: str
    """新闻舆情分析报告"""

    fundamentals_report: str
    """基本面分析报告"""

    # ── 投资辩论 ────────────────────────────────────────────
    investment_debate_state: InvestDebateState | None
    """多空辩论子状态"""

    investment_plan: str
    """研究员综合投资方案（辩论产出）"""

    # ── 交易员方案 ──────────────────────────────────────────
    trader_investment_plan: str
    """交易员基于研究员方案制定的具体交易计划"""

    # ── 风控辩论 ────────────────────────────────────────────
    risk_debate_state: RiskDebateState | None
    """风控三方辩论子状态"""

    # ── 最终决策 ────────────────────────────────────────────
    final_trade_decision: str
    """基金经理最终交易决策"""

    # ── 历史记忆 ────────────────────────────────────────────
    past_context: str
    """从记忆日志中加载的历史交易上下文"""

    # ── 报告产出 ────────────────────────────────────────────
    report_path: str
    """生成的 HTML 报告文件路径"""
