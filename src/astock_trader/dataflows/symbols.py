"""A 股代码规范化 —— 各数据源对代码写法的要求不同，集中在这里转换。

Tushare 用 ``600519.SH``，新浪/腾讯行情用 ``sh600519``，akshare 的东财接口
用裸 6 位 ``600519``。把转换逻辑收拢到一处，避免每个数据源各写一份 zfill 分支。
"""

from __future__ import annotations

__all__ = ["to_prefixed_code", "to_bare_code"]

# 沪市：60 主板 / 68 科创板 / 5 基金 / 11 可转债
_SH_PREFIXES = ("60", "68", "5", "11")
# 北交所：43 / 83 / 87 存量，92 新号段
_BJ_PREFIXES = ("43", "83", "87", "92")


def to_prefixed_code(symbol: str) -> str:
    """把 6 位 A 股代码转成带交易所前缀的行情代码。

    ``600519 -> sh600519``、``000001 -> sz000001``、``430047 -> bj430047``。
    已带前缀的原样返回（统一小写），``600519.SH`` 这类 Tushare 写法也接受。
    """
    raw = str(symbol).strip().lower()
    if raw.startswith(("sh", "sz", "bj")) and len(raw) == 8:
        return raw
    # 兼容 Tushare 的 600519.SH 写法
    code = raw.split(".")[0]
    exchange = raw.split(".")[1] if "." in raw else ""
    if exchange in {"sh", "sz", "bj"}:
        return f"{exchange}{code.zfill(6)}"
    code = code.zfill(6)
    if code.startswith(_SH_PREFIXES):
        prefix = "sh"
    elif code.startswith(_BJ_PREFIXES):
        prefix = "bj"
    else:
        prefix = "sz"
    return f"{prefix}{code}"


def to_bare_code(symbol: str) -> str:
    """去掉交易所前缀／后缀，返回 6 位裸代码。

    ``sh600519 -> 600519``、``600519.SH -> 600519``、``600519 -> 600519``。
    """
    raw = str(symbol).strip().lower()
    if raw.startswith(("sh", "sz", "bj")) and len(raw) == 8:
        return raw[2:]
    return raw.split(".")[0].zfill(6)
