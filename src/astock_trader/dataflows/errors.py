"""数据源错误层级 — 让路由层按**行为**反应，而不是按厂商逐个判断。

.. code-block:: text

    VendorError
    ├── NoMarketDataError          没有可用数据（空结果或数据陈旧）
    ├── VendorRateLimitError       限流／配额用尽 → 换下一个数据源
    └── VendorNotConfiguredError   缺 API Key 或依赖未安装 → 该数据源不可用

类型数量 = 路由层的**不同反应**数量，不是「人能数出来的原因」数量：空数据和
陈旧数据的处理完全一样，所以共用一个 :class:`NoMarketDataError`，只在
``detail`` 里区分。新增数据源抛这些类型即可，路由层不需要新增 ``except`` 分支。

用法
----
数据源函数在**不可用**时应当抛异常，而不是返回一段错误文本 ——
:func:`~astock_trader.dataflows.interface.route_to_vendor` 会捕获并自动换到
下一个数据源，同时按类型给出合适的日志级别（缺 key 是预期内的，不该刷 warning）。

历史遗留的软失败路径仍会返回 ``"[ERROR] ..."`` 字符串，路由层同样会识别并换源
（见 :func:`is_failure_payload`）；但字符串写法丢了分类信息，迁移到抛异常能得到
更准确的日志级别与更清晰的原因。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "NoMarketDataError",
    "VendorError",
    "VendorNotConfiguredError",
    "VendorRateLimitError",
    "is_failure_payload",
]

# 各数据源在软失败路径上统一使用的标记。只有失败路径才会出现它。
_FAILURE_MARKER = "[ERROR]"


class VendorError(Exception):
    """数据源无法返回可用数据时的基类。"""


class NoMarketDataError(VendorError):
    """数据源对该标的没有可用数据（空结果或数据陈旧）。

    同时携带用户请求的代码与数据源实际查询的代码，以及自由文本 ``detail``，
    这样调用方能拼出一句清楚的话，而不是把厂商特有的空字符串丢进数据通道。
    """

    def __init__(self, symbol: str, canonical: str | None = None, detail: str = ""):
        self.symbol = symbol
        self.canonical = canonical or symbol
        self.detail = detail
        message = f"No market data for {symbol!r}"
        if canonical and canonical != symbol:
            message += f" (queried as {canonical!r})"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class VendorRateLimitError(VendorError):
    """数据源限流或配额用尽；路由层换到下一个数据源。"""


class VendorNotConfiguredError(VendorError, ValueError):
    """选中了某个数据源，但它缺少 API Key／依赖。

    同时继承 ``ValueError``，让历史上捕获 ``ValueError`` 的调用点继续可用，
    而路由层可以把它当成「该数据源不可用」处理。
    """


def is_failure_payload(payload: Any) -> bool:
    """返回值是否是数据源的**软失败**标记串。

    边界很窄，只认 ``[ERROR]`` 标记：

    * 本项目所有数据源只在失败路径上写 ``[ERROR]``，所以命中即失败；
    * 「查询成功但该标的没有数据」这类**信息性**返回（例如
      ``"... No data returned for ..."``）**不算**失败 —— 它和数据源故障是两回
      事，混在一起判断会把「这只股票确实没有财报」误报成「数据源挂了」。
      真想让路由层在这类情况下换源的数据源，应当抛 :class:`NoMarketDataError`。
    """
    return isinstance(payload, str) and _FAILURE_MARKER in payload
