"""Agent utility functions — 通用工具函数集合。

包含构建股票上下文、语言指令、消息清理等辅助功能。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_instrument_context(
    stock_code: str,
    stock_name: str = "",
    exchange: str = "",
    industry: str = "",
) -> str:
    """构建股票标的上下文信息字符串。

    Parameters
    ----------
    stock_code : str
        股票代码，如 ``"000001"`` 或 ``"600519"``。
    stock_name : str
        股票名称，如 ``"平安银行"``。
    exchange : str
        交易所，如 ``"深圳证券交易所"`` 或 ``"上海证券交易所"``。
    industry : str
        所属行业。

    Returns
    -------
    str
        格式化的标的上下文文本。
    """
    parts = [f"股票代码: {stock_code}"]
    if stock_name:
        parts.append(f"股票名称: {stock_name}")
    if exchange:
        parts.append(f"交易所: {exchange}")
    if industry:
        parts.append(f"所属行业: {industry}")
    return "\n".join(parts)


def get_language_instruction(language: str = "Chinese") -> str:
    """获取输出语言指令提示词。

    Parameters
    ----------
    language : str
        目标语言标识，默认 ``"Chinese"``。

    Returns
    -------
    str
        语言指令提示词片段。
    """
    instructions = {
        "Chinese": "请使用简体中文输出你的分析结果。",
        "English": "Please output your analysis in English.",
        "Japanese": "日本語で分析結果を出力してください。",
    }
    return instructions.get(language, f"请使用{language}输出你的分析结果。")


def create_msg_delete(agent_name: str = "") -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """创建一个消息清理函数，用于清除历史消息并添加继续占位符。

    在辩论场景中，当需要将长对话历史压缩为单条摘要消息时使用。

    Parameters
    ----------
    agent_name : str
        Agent 名称，用于生成占位符消息内容。

    Returns
    -------
    Callable
        接受状态字典、返回修改后状态字典的函数。
    """
    label = agent_name or "Agent"

    def _clear_messages(state: Dict[str, Any]) -> Dict[str, Any]:
        """清除 messages 列表并添加一条 Continue 占位符。"""
        placeholder = {
            "role": "assistant",
            "content": f"[{label}] 已清理历史消息，请基于上方摘要继续分析。",
        }
        return {"messages": [placeholder]}

    return _clear_messages


def format_number(value: Optional[float], precision: int = 2) -> str:
    """格式化数字为中文习惯的字符串表示。

    Parameters
    ----------
    value : float | None
        数值。
    precision : int
        小数精度，默认 2 位。

    Returns
    -------
    str
        格式化后的字符串；若 value 为 None 返回 ``"N/A"``。
    """
    if value is None:
        return "N/A"
    return f"{value:,.{precision}f}"


def truncate_text(text: str, max_length: int = 2000, suffix: str = "...") -> str:
    """截断超长文本。

    Parameters
    ----------
    text : str
        原始文本。
    max_length : int
        最大字符数，默认 2000。
    suffix : str
        截断后缀标记。

    Returns
    -------
    str
        截断后的文本。
    """
    if not text or len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
