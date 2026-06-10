"""Tushare 金融数据适配器 — 专业级A股结构化数据源。

通过 Tushare Pro REST API 提供：
- 每日行情与基本面指标（PE/PB/市值/换手率/股息率）
- 三大财务报表（利润表/资产负债表/现金流量表）
- 财务指标（ROE/ROA/毛利率/净利率/资产周转率等）
- 资金流向（大单/小单/超大单分析）
- 股东信息（十大股东/十大流通股东/股东增减持）
- 业绩预告与快报
- 分红送股数据
- 融资融券数据
- 新闻资讯

API 认证：环境变量 TUSHARE_TOKEN，也可复用 MCP 配置中的 token。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "http://api.tushare.pro"
_TIMEOUT = 30


# ---------------------------------------------------------------------------
#  辅助函数
# ---------------------------------------------------------------------------

def _get_token() -> str:
    """获取 Tushare API Token。必须通过环境变量 TUSHARE_TOKEN 设置。"""
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise EnvironmentError(
            "未找到 Tushare API Token。请设置环境变量 TUSHARE_TOKEN，"
            "可在 https://tushare.pro/register 注册获取。"
        )
    return token


def _to_ts_code(symbol: str) -> str:
    """将6位股票代码转换为 Tushare ts_code 格式。

    Examples:
        600519 -> 600519.SH
        000001 -> 000001.SZ
        300750 -> 300750.SZ
        688981 -> 688981.SH
        600519.SH -> 600519.SH (already formatted)
    """
    symbol = symbol.strip()
    if "." in symbol:
        return symbol.upper()
    code = symbol.lstrip("0")
    if symbol.startswith(("6", "9", "11")):
        return f"{symbol}.SH"
    return f"{symbol}.SZ"


def _from_ts_code(ts_code: str) -> str:
    """600519.SH -> 600519"""
    return ts_code.split(".")[0] if "." in ts_code else ts_code


def _call_api(api_name: str, params: dict[str, Any] | None = None,
              fields: str | None = None) -> dict:
    """调用 Tushare Pro REST API。"""
    token = _get_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未设置。请配置环境变量。")

    payload: dict[str, Any] = {
        "api_name": api_name,
        "token": token,
        "params": params or {},
    }
    if fields:
        payload["fields"] = fields

    resp = requests.post(_BASE_URL, json=payload, timeout=_TIMEOUT)
    result = resp.json()

    code = result.get("code", -1)
    if code != 0:
        msg = result.get("msg", "未知错误")
        raise RuntimeError(f"Tushare API 错误 ({api_name}): {msg}")

    return result.get("data", {})


def _data_to_markdown(data: dict, title: str = "", max_rows: int = 30) -> str:
    """将 Tushare 返回的 {fields, items} 结构转为可读 Markdown 表格。"""
    fields = data.get("fields", [])
    items = data.get("items", [])

    if not fields or not items:
        return f"{title}\n（无数据）" if title else "（无数据）"

    # 字段名映射：英文 -> 中文
    field_labels = _get_field_labels(fields)
    headers = [field_labels.get(f, f) for f in fields]

    lines = []
    if title:
        lines.append(f"### {title}")
        lines.append("")

    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in items[:max_rows]:
        cells = [_format_cell(f, v) for f, v in zip(fields, row)]
        lines.append("| " + " | ".join(cells) + " |")

    if len(items) > max_rows:
        lines.append(f"\n*（共 {len(items)} 行，仅显示前 {max_rows} 行）*")

    return "\n".join(lines)


def _format_cell(field: str, value: Any) -> str:
    """格式化单元格值。"""
    if value is None:
        return ""
    # 持股数量字段（股）
    if field in _SHARE_FIELDS and isinstance(value, (int, float)):
        if abs(value) >= 1e8:
            return f"{value / 1e8:.2f}亿股"
        if abs(value) >= 1e4:
            return f"{value / 1e4:.2f}万股"
        return f"{value:.0f}股"
    # 股本字段（万股）
    if field in _SHARE_CAPITAL_FIELDS and isinstance(value, (int, float)):
        if abs(value) >= 1e4:
            return f"{value / 1e4:.2f}亿股"
        return f"{value:.2f}万股"
    # 金额类字段（万元）-> 亿元
    if field in _MONEY_FIELDS and isinstance(value, (int, float)):
        if abs(value) >= 10000:
            return f"{value / 10000:.2f}亿"
        return f"{value:.2f}万"
    # 百分比类字段
    if field in _PCT_FIELDS and isinstance(value, (int, float)):
        return f"{value:.2f}%"
    # 浮点数保留4位
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 1 else f"{value:.2f}"
    return str(value)


# 持股数量字段（股单位）
_SHARE_FIELDS = {
    "hold_amount", "change_vol", "after_share",
}

# 股本字段（万股单位）
_SHARE_CAPITAL_FIELDS = {
    "total_share", "float_share", "free_share",
}


# 金额字段（万元单位）— 仅限真正的金额字段
_MONEY_FIELDS = {
    "total_revenue", "revenue", "total_cogs", "oper_cost", "n_income",
    "n_income_attr_p", "operate_profit", "total_profit", "total_mv",
    "circ_mv", "buy_sm_amount", "sell_sm_amount", "buy_md_amount",
    "sell_md_amount", "buy_lg_amount", "sell_lg_amount", "buy_elg_amount",
    "sell_elg_amount", "net_mf_amount",
    "buy_amount", "sell_amount", "total_amount",
    "total_assets", "total_liab", "money_cap", "accounts_receiv",
    "inventories", "fix_assets",
    "n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act",
    "c_fr_sale_sg", "c_pay_dist_dpcp_int_exp",
    "net_profit_min", "net_profit_max", "last_parent_net",
}

# 百分比字段（值为真实百分比，如 52.22 表示 52.22%）
_PCT_FIELDS = {
    "turnover_rate", "turnover_rate_f", "dv_ratio", "dv_ttm",
    "p_change_min", "p_change_max", "pct_chg",
    "change_ratio", "hold_ratio", "hold_float_ratio",
    "roe", "roe_waa", "roe_dt", "roa", "roic", "npta",
    "gross_margin", "netprofit_margin", "grossprofit_margin",
    "debt_to_assets", "current_ratio", "quick_ratio",
    "q_roe", "q_dt_roe", "q_npta",
    "netprofit_yoy", "or_yoy", "q_netprofit_yoy",
}


def _get_field_labels(fields: list[str]) -> dict[str, str]:
    """为常见字段提供中文标签。"""
    label_map = {
        # 行情
        "ts_code": "代码", "trade_date": "日期", "close": "收盘价",
        "open": "开盘价", "high": "最高价", "low": "最低价",
        "pre_close": "昨收", "change": "涨跌额", "pct_chg": "涨跌幅%",
        "vol": "成交量(手)", "amount": "成交额(千元)",
        # 每日指标
        "turnover_rate": "换手率%", "turnover_rate_f": "自由换手率%",
        "volume_ratio": "量比", "pe": "PE", "pe_ttm": "PE(TTM)",
        "pb": "PB", "ps": "PS", "ps_ttm": "PS(TTM)",
        "dv_ratio": "股息率%", "dv_ttm": "股息率%(TTM)",
        "total_share": "总股本(万股)", "float_share": "流通股本(万股)",
        "free_share": "自由流通股本(万)", "total_mv": "总市值(万元)",
        "circ_mv": "流通市值(万元)",
        # 财务
        "ann_date": "公告日期", "end_date": "报告期", "f_ann_date": "实际公告日",
        "report_type": "报告类型", "comp_type": "公司类型",
        "basic_eps": "基本EPS", "diluted_eps": "稀释EPS",
        "total_revenue": "营业总收入", "revenue": "营业收入",
        "total_cogs": "营业总成本", "oper_cost": "营业成本",
        "sell_exp": "销售费用", "admin_exp": "管理费用", "fin_exp": "财务费用",
        "rd_exp": "研发费用", "operate_profit": "营业利润",
        "total_profit": "利润总额", "income_tax": "所得税",
        "n_income": "净利润", "n_income_attr_p": "归属母公司净利润",
        "ebit": "EBIT", "ebitda": "EBITDA",
        # 资产负债表
        "total_assets": "总资产", "total_liab": "总负债",
        "total_hldr_eqy_exc_min_int": "股东权益(不含少数)",
        "total_hldr_eqy_inc_min_int": "股东权益(含少数)",
        "total_cur_assets": "流动资产合计", "total_cur_liab": "流动负债合计",
        "total_nca": "非流动资产合计", "total_ncl": "非流动负债合计",
        "money_cap": "货币资金", "accounts_receiv": "应收账款",
        "inventories": "存货", "fix_assets": "固定资产",
        # 现金流
        "n_cashflow_act": "经营活动现金流净额",
        "n_cashflow_inv_act": "投资活动现金流净额",
        "n_cash_flows_fnc_act": "筹资活动现金流净额",
        "c_fr_sale_sg": "销售商品收到的现金",
        "c_pay_dist_dpcp_int_exp": "分配股利利润偿付利息",
        # 财务指标
        "eps": "每股收益", "dt_eps": "扣非EPS",
        "gross_margin": "毛利率%", "netprofit_margin": "净利率%",
        "roe": "ROE%", "roe_waa": "加权ROE%", "roe_dt": "扣非ROE%",
        "roa": "ROA%", "roic": "ROIC%",
        "current_ratio": "流动比率", "quick_ratio": "速动比率",
        "debt_to_assets": "资产负债率%",
        "or_yoy": "营收同比增长%", "netprofit_yoy": "净利润同比增长%",
        "q_roe": "单季度ROE%", "q_netprofit_yoy": "单季度净利润同比%",
        # 资金流向
        "buy_sm_vol": "小单买入量", "buy_sm_amount": "小单买入额",
        "sell_sm_vol": "小单卖出量", "sell_sm_amount": "小单卖出额",
        "buy_md_vol": "中单买入量", "buy_md_amount": "中单买入额",
        "sell_md_vol": "中单卖出量", "sell_md_amount": "中单卖出额",
        "buy_lg_vol": "大单买入量", "buy_lg_amount": "大单买入额",
        "sell_lg_vol": "大单卖出量", "sell_lg_amount": "大单卖出额",
        "buy_elg_vol": "超大单买入量", "buy_elg_amount": "超大单买入额",
        "sell_elg_vol": "超大单卖出量", "sell_elg_amount": "超大单卖出额",
        "net_mf_vol": "净流入量", "net_mf_amount": "净流入额",
        # 股东
        "holder_name": "股东名称", "hold_amount": "持股数量",
        "hold_ratio": "持股比例%", "hold_float_ratio": "流通持股比%",
        "hold_change": "持股变动", "holder_type": "股东类型",
        "in_de": "增减持", "change_vol": "变动数量",
        "change_ratio": "变动比例", "after_share": "变动后持股",
        "after_ratio": "变动后比例", "avg_price": "均价",
        # 业绩预告
        "type": "预告类型", "p_change_min": "预计变动下限%",
        "p_change_max": "预计变动上限%", "net_profit_min": "预计净利润下限",
        "net_profit_max": "预计净利润上限", "summary": "预告摘要",
        "change_reason": "变动原因",
        # 分红
        "stk_div": "每股送股", "cash_div": "每股分红(元)",
        "record_date": "股权登记日", "ex_date": "除权除息日",
        "div_listdate": "分红上市日", "base_date": "分红基准日",
        # 新闻
        "datetime": "时间", "title": "标题", "content": "内容",
        "channels": "来源",
    }
    return {f: label_map.get(f, f) for f in fields}


def _safe_call(func):
    """统一错误包装装饰器。"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RuntimeError as e:
            return f"[ERROR] {e}"
        except requests.exceptions.Timeout:
            return f"[ERROR] Tushare API 请求超时（{_TIMEOUT}s）"
        except requests.exceptions.ConnectionError:
            return "[ERROR] Tushare API 连接失败，请检查网络"
        except Exception as exc:
            return f"[ERROR] Tushare API 调用异常: {exc}"
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


# ---------------------------------------------------------------------------
# 公开数据函数
# ---------------------------------------------------------------------------

@_safe_call
def get_daily_basic(
    symbol: Annotated[str, "A股股票代码，如 600519"],
    start_date: Annotated[str, "开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取每日基本面指标（PE/PB/市值/换手率/股息率等）。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("daily_basic", params)
    return f"# {symbol} 每日基本面指标（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 每日指标')}"


@_safe_call
def get_fina_indicator(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "报告期开始 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "报告期结束 yyyy-mm-dd"] = "",
) -> str:
    """获取详细财务指标（ROE/ROA/毛利率/净利率/资产周转率等）。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("fina_indicator", params)
    return f"# {symbol} 财务指标（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 财务指标')}"


@_safe_call
def get_income(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "报告期开始 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "报告期结束 yyyy-mm-dd"] = "",
) -> str:
    """获取利润表数据（Tushare 结构化数据）。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("income", params)
    return f"# {symbol} 利润表（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 利润表')}"


@_safe_call
def get_balance_sheet(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "报告期开始 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "报告期结束 yyyy-mm-dd"] = "",
) -> str:
    """获取资产负债表（Tushare 结构化数据）。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("balancesheet", params)
    return f"# {symbol} 资产负债表（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 资产负债表')}"


@_safe_call
def get_cashflow(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "报告期开始 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "报告期结束 yyyy-mm-dd"] = "",
) -> str:
    """获取现金流量表（Tushare 结构化数据）。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("cashflow", params)
    return f"# {symbol} 现金流量表（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 现金流量表')}"


@_safe_call
def get_moneyflow(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取个股资金流向（大单/中单/小单/超大单分析）。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("moneyflow", params)
    return f"# {symbol} 资金流向（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 资金流向')}"


@_safe_call
def get_top10_holders(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "报告期开始 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "报告期结束 yyyy-mm-dd"] = "",
) -> str:
    """获取前十大股东数据。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("top10_holders", params)
    return f"# {symbol} 前十大股东（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 前十大股东')}"


@_safe_call
def get_top10_floatholders(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "报告期开始 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "报告期结束 yyyy-mm-dd"] = "",
) -> str:
    """获取前十大流通股东数据。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("top10_floatholders", params)
    return f"# {symbol} 前十大流通股东（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 前十大流通股东')}"


@_safe_call
def get_holdertrade(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "公告开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "公告结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取股东增减持数据。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("stk_holdertrade", params)
    return f"# {symbol} 股东增减持（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 股东增减持')}"


@_safe_call
def get_forecast(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "公告开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "公告结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取业绩预告数据（预增/预减/扭亏/首亏等）。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("forecast", params)
    return f"# {symbol} 业绩预告（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 业绩预告')}"


@_safe_call
def get_express(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "公告开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "公告结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取业绩快报数据。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("express", params)
    return f"# {symbol} 业绩快报（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 业绩快报')}"


@_safe_call
def get_dividend(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "公告开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "公告结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取分红送股数据。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["ann_start_date"] = start_date.replace("-", "")
    if end_date:
        params["ann_end_date"] = end_date.replace("-", "")

    data = _call_api("dividend", params)
    return f"# {symbol} 分红送股（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 分红送股')}"


@_safe_call
def get_news(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取新闻快讯。"""
    params: dict[str, Any] = {}
    if start_date:
        params["start_date"] = start_date.replace("-", "") + " 00:00:00"
    if end_date:
        params["end_date"] = end_date.replace("-", "") + " 23:59:59"
    if not params:
        # 默认最近7天
        from datetime import datetime, timedelta
        now = datetime.now()
        params["start_date"] = (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
        params["end_date"] = now.strftime("%Y-%m-%d 23:59:59")

    data = _call_api("news", params)
    fields = data.get("fields", [])
    items = data.get("items", [])

    if not items:
        return f"[Tushare] 未找到相关新闻。"

    parts = [f"### Tushare 新闻快讯（共 {len(items)} 条）", ""]
    for i, row in enumerate(items[:20]):
        row_dict = dict(zip(fields, row))
        title = row_dict.get("title", "无标题")
        dt = row_dict.get("datetime", "")
        channels = row_dict.get("channels", "")
        content = row_dict.get("content", "")

        meta = " | ".join(filter(None, [dt, channels]))
        parts.append(f"**{i+1}. {title}**")
        if meta:
            parts.append(f"   {meta}")
        if content:
            snippet = content[:200] + "..." if len(content) > 200 else content
            parts.append(f"   {snippet}")
        parts.append("")

    return "\n".join(parts)


@_safe_call
def get_fundamentals(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    curr_date: Annotated[str, "当前日期（可选）"] = None,
) -> str:
    """通过 Tushare 获取公司基本面综合数据（每日指标 + 最新财务指标）。"""
    ts_code = _to_ts_code(symbol)

    parts = [f"# {symbol} 基本面数据（Tushare）", ""]

    # 1. 每日基本面指标（最近5个交易日）
    try:
        daily_data = _call_api("daily_basic", {"ts_code": ts_code})
        parts.append(_data_to_markdown(daily_data, "每日估值指标", max_rows=5))
    except Exception as e:
        parts.append(f"每日指标获取失败: {e}")

    parts.append("")

    # 2. 最新财务指标（最近2期）
    try:
        fina_data = _call_api("fina_indicator", {"ts_code": ts_code})
        parts.append(_data_to_markdown(fina_data, "财务指标", max_rows=2))
    except Exception as e:
        parts.append(f"财务指标获取失败: {e}")

    return "\n\n".join(parts)


@_safe_call
def get_margin_detail(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取融资融券交易明细。"""
    ts_code = _to_ts_code(symbol)
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    data = _call_api("margin_detail", params)
    return f"# {symbol} 融资融券明细（Tushare）\n\n{_data_to_markdown(data, f'{symbol} 融资融券')}"
