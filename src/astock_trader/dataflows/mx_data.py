"""妙想 (MX) 金融数据适配器 — 东方财富权威数据源。

通过妙想 API 提供：
- 自然语言金融数据查询（行情/财务/估值/股东等）
- 资讯搜索（新闻/公告/研报/政策）
- 智能选股

API 认证：环境变量 MX_APIKEY，通过 HTTP Header ``apikey`` 传递。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://mkapi2.dfcfs.com"
_TIMEOUT = 30


def _get_api_key() -> str | None:
    """从环境变量获取 API Key。"""
    key = os.environ.get("MX_APIKEY")
    if not key:
        logger.warning("MX_APIKEY 环境变量未设置，妙想 API 不可用。")
    return key


def _headers() -> dict[str, str]:
    key = _get_api_key()
    if not key:
        raise RuntimeError("MX_APIKEY 环境变量未设置。请先配置：export MX_APIKEY=your-key")
    return {
        "apikey": key,
        "Content-Type": "application/json",
    }


def _safe_call(func):
    """统一错误包装装饰器。"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RuntimeError:
            raise
        except requests.exceptions.Timeout:
            return f"[ERROR] 妙想 API 请求超时（{_TIMEOUT}s）"
        except requests.exceptions.ConnectionError:
            return "[ERROR] 妙想 API 连接失败，请检查网络"
        except Exception as exc:
            return f"[ERROR] 妙想 API 调用异常: {exc}"
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def _parse_data_tables(result: dict) -> str:
    """解析 API 返回的 dataTableDTOList 为可读 Markdown。

    妙想 API 的数据路径为:
    result -> data -> data -> searchDataResultDTO -> dataTableDTOList
    或 result -> data -> dataTableDTOList (两种结构都兼容)

    每个 table 条目包含:
    - table:         {column_id: [formatted_strings...]}  已格式化（如 "281.5亿元"）
    - rawTable:      {column_id: [raw_values...]}         原始数值
    - nameMap:       {column_id: "中文列名"}              列 ID → 可读名称映射
    - headNameSub:   列头含义说明（如 "数据来源"）
    """
    # 尝试多种数据路径
    tables = []

    # 路径 1: data.data.searchDataResultDTO.dataTableDTOList
    inner = result.get("data", {})
    if isinstance(inner, dict):
        inner_data = inner.get("data", {})
        if isinstance(inner_data, dict):
            search_dto = inner_data.get("searchDataResultDTO", {})
            if isinstance(search_dto, dict):
                tables = search_dto.get("dataTableDTOList", [])

    # 路径 2: data.dataTableDTOList (fallback)
    if not tables:
        tables = inner.get("dataTableDTOList", [])

    if not tables:
        msg = result.get("message", "") or result.get("msg", "")
        return f"[妙想] 无数据返回。{msg}" if msg else "[妙想] 无数据返回。"

    parts = []
    for i, tbl in enumerate(tables):
        code = tbl.get("code", "")
        entity = tbl.get("entityName", code or f"数据表 {i+1}")

        # --- 列名映射：优先 nameMap，其次 columnMetaList ---
        name_map: dict[str, str] = tbl.get("nameMap", {}) or {}

        # 兼容旧逻辑：columnMetaList / columns 备选
        col_meta = tbl.get("columnMetaList", []) or tbl.get("columns", [])
        for cm in col_meta:
            cid = cm.get("columnId", cm.get("id", ""))
            cname = cm.get("columnName", cm.get("name", cid))
            if cid and cid not in name_map:
                name_map[cid] = cname

        # --- 数据源：优先 table（已格式化），fallback rawTable ---
        data_table = tbl.get("table", {}) or {}
        if not data_table:
            data_table = tbl.get("rawTable", {}) or {}

        if not data_table:
            parts.append(f"### {entity}\n（无数据）")
            continue

        # 构建表格列
        col_ids = list(data_table.keys())

        # 用 name_map 翻译列名；对 headName 保留原名（通常是日期列表）
        def _display_name(cid: str) -> str:
            if cid in name_map:
                return name_map[cid]
            # headName / headNameSub 是内置日期/来源列
            if cid == "headName":
                return "报告期"
            if cid == "headNameSub":
                return tbl.get("headNameSub", "") or "数据来源"
            return cid

        headers = [_display_name(cid) for cid in col_ids]
        max_rows = (
            max(len(v) if isinstance(v, list) else 1 for v in data_table.values())
            if data_table
            else 0
        )

        lines = [f"### {entity}", ""]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row_idx in range(min(max_rows, 30)):
            cells = []
            for cid in col_ids:
                col_data = data_table.get(cid, [])
                if isinstance(col_data, list) and row_idx < len(col_data):
                    cells.append(str(col_data[row_idx]))
                else:
                    cells.append("")
            lines.append("| " + " | ".join(cells) + " |")

        if max_rows > 30:
            lines.append(f"\n*（共 {max_rows} 行，仅显示前 30 行）*")

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _parse_search_results(result: dict) -> str:
    """解析资讯搜索结果。"""
    data = result.get("data", {}).get("data", {})
    items = data.get("llmSearchResponse", {}).get("data", [])
    if not items:
        msg = result.get("message", "")
        return f"[妙想] 未找到相关资讯。{msg}" if msg else "[妙想] 未找到相关资讯。"

    parts = [f"### 妙想资讯搜索（共 {len(items)} 条）", ""]
    for i, item in enumerate(items[:15]):
        title = item.get("title", "无标题")
        source = item.get("insName", "")
        date = item.get("date", "")
        info_type = item.get("informationType", "")
        content = item.get("content", "")
        rating = item.get("rating", "")

        meta = []
        if source:
            meta.append(source)
        if date:
            meta.append(date[:10])
        if info_type:
            meta.append(info_type)
        if rating:
            meta.append(f"评级: {rating}")

        meta_str = " | ".join(meta) if meta else ""
        parts.append(f"**{i+1}. {title}**")
        if meta_str:
            parts.append(f"   {meta_str}")
        if content:
            # 截取前200字
            snippet = content[:200] + "..." if len(content) > 200 else content
            parts.append(f"   {snippet}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 公开数据函数 — 与 akshare_data.py 接口对齐
# ---------------------------------------------------------------------------

@_safe_call
def get_fundamentals(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    curr_date: Annotated[str, "当前日期（可选）"] = None,
) -> str:
    """通过妙想 API 查询公司基本面数据（自然语言查询）。"""
    query = f"{symbol} 公司基本面 市值 PE PB ROE 营收 净利润 主营业务"
    resp = requests.post(
        f"{BASE_URL}/finskillshub/api/claw/query",
        headers=_headers(),
        json={"toolQuery": query},
        timeout=_TIMEOUT,
    )
    result = resp.json()
    status = result.get("status", -1)
    if status != 0:
        code = result.get("code", "")
        msg = result.get("message", "未知错误")
        if code == 113:
            return f"[ERROR] 妙想 API 调用次数已达上限。"
        if code == 114:
            return f"[ERROR] 妙想 API Key 已失效，请检查 MX_APIKEY。"
        return f"[ERROR] 妙想 API 返回错误 (status={status}, code={code}): {msg}"
    return f"# {symbol} 基本面数据（妙想）\n\n{_parse_data_tables(result)}"


@_safe_call
def get_balance_sheet(
    symbol: Annotated[str, "A股股票代码"],
    freq: Annotated[str, "频率 annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "当前日期"] = None,
) -> str:
    """通过妙想 API 查询资产负债表。"""
    freq_cn = "季度" if freq == "quarterly" else "年度"
    query = f"{symbol} {freq_cn}资产负债表 总资产 总负债 股东权益 流动资产 流动负债"
    resp = requests.post(
        f"{BASE_URL}/finskillshub/api/claw/query",
        headers=_headers(),
        json={"toolQuery": query},
        timeout=_TIMEOUT,
    )
    result = resp.json()
    if result.get("status", -1) != 0:
        return f"[ERROR] 妙想资产负债表查询失败: {result.get('message', '')}"
    return f"# {symbol} 资产负债表（妙想）\n\n{_parse_data_tables(result)}"


@_safe_call
def get_cashflow(
    symbol: Annotated[str, "A股股票代码"],
    freq: Annotated[str, "频率 annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "当前日期"] = None,
) -> str:
    """通过妙想 API 查询现金流量表。"""
    freq_cn = "季度" if freq == "quarterly" else "年度"
    query = f"{symbol} {freq_cn}现金流量表 经营活动 投资活动 筹资活动 现金净增加"
    resp = requests.post(
        f"{BASE_URL}/finskillshub/api/claw/query",
        headers=_headers(),
        json={"toolQuery": query},
        timeout=_TIMEOUT,
    )
    result = resp.json()
    if result.get("status", -1) != 0:
        return f"[ERROR] 妙想现金流量查询失败: {result.get('message', '')}"
    return f"# {symbol} 现金流量表（妙想）\n\n{_parse_data_tables(result)}"


@_safe_call
def get_income_statement(
    symbol: Annotated[str, "A股股票代码"],
    freq: Annotated[str, "频率 annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "当前日期"] = None,
) -> str:
    """通过妙想 API 查询利润表。"""
    freq_cn = "季度" if freq == "quarterly" else "年度"
    query = f"{symbol} {freq_cn}利润表 营业收入 营业成本 毛利润 净利润 每股收益"
    resp = requests.post(
        f"{BASE_URL}/finskillshub/api/claw/query",
        headers=_headers(),
        json={"toolQuery": query},
        timeout=_TIMEOUT,
    )
    result = resp.json()
    if result.get("status", -1) != 0:
        return f"[ERROR] 妙想利润表查询失败: {result.get('message', '')}"
    return f"# {symbol} 利润表（妙想）\n\n{_parse_data_tables(result)}"


@_safe_call
def get_news(
    symbol: Annotated[str, "A股股票代码"],
    start_date: Annotated[str, "开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "结束日期 yyyy-mm-dd"] = "",
) -> str:
    """通过妙想 API 搜索个股新闻和资讯。"""
    query = f"{symbol} 最新新闻 公告 研报"
    resp = requests.post(
        f"{BASE_URL}/finskillshub/api/claw/news-search",
        headers=_headers(),
        json={"query": query},
        timeout=_TIMEOUT,
    )
    result = resp.json()
    if result.get("status", -1) != 0:
        return f"[ERROR] 妙想资讯搜索失败: {result.get('message', '')}"
    return _parse_search_results(result)


@_safe_call
def get_global_news(
    curr_date: Annotated[str, "当前日期 yyyy-mm-dd"] = "",
    look_back_days: Annotated[int, "回看天数"] = 7,
    limit: Annotated[int, "最大返回条数"] = 5,
) -> str:
    """通过妙想 API 搜索全市场宏观新闻。"""
    query = "A股市场 宏观经济 政策 最新动态"
    resp = requests.post(
        f"{BASE_URL}/finskillshub/api/claw/news-search",
        headers=_headers(),
        json={"query": query},
        timeout=_TIMEOUT,
    )
    result = resp.json()
    if result.get("status", -1) != 0:
        return f"[ERROR] 妙想全球新闻搜索失败: {result.get('message', '')}"
    return _parse_search_results(result)


@_safe_call
def get_stock_valuation(
    symbol: Annotated[str, "A股股票代码"],
    curr_date: Annotated[str, "当前日期"] = None,
) -> str:
    """通过妙想 API 查询股票估值数据（PE/PB/PS/股息率等）。"""
    query = f"{symbol} 估值 PE TTM PB PS 股息率 历史分位"
    resp = requests.post(
        f"{BASE_URL}/finskillshub/api/claw/query",
        headers=_headers(),
        json={"toolQuery": query},
        timeout=_TIMEOUT,
    )
    result = resp.json()
    if result.get("status", -1) != 0:
        return f"[ERROR] 妙想估值查询失败: {result.get('message', '')}"
    return f"# {symbol} 估值数据（妙想）\n\n{_parse_data_tables(result)}"


@_safe_call
def get_shareholder_info(
    symbol: Annotated[str, "A股股票代码"],
    curr_date: Annotated[str, "当前日期"] = None,
) -> str:
    """通过妙想 API 查询股东和持股变动信息。"""
    query = f"{symbol} 十大股东 持股变动 机构持仓"
    resp = requests.post(
        f"{BASE_URL}/finskillshub/api/claw/query",
        headers=_headers(),
        json={"toolQuery": query},
        timeout=_TIMEOUT,
    )
    result = resp.json()
    if result.get("status", -1) != 0:
        return f"[ERROR] 妙想股东查询失败: {result.get('message', '')}"
    return f"# {symbol} 股东信息（妙想）\n\n{_parse_data_tables(result)}"
