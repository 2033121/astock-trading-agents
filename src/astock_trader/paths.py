"""统一的落盘路径解析 —— 所有输出目录都从**一个根**派生。

历史上 ``~/.astock_trader`` 被硬编码在九个模块里（config、CLI、图、记忆、
监控台账、外部校准、MCP server……），改一次根目录要动九处，漏一处就会出现
「报告写在新盘、记忆还在旧盘」这种半迁移状态。

现在只有 :func:`resolve_project_dir` 知道根在哪，其余一律 ``project_dir()``
派生。解析顺序：

1. 环境变量 ``ASTOCK_HOME``（显式指定，最高优先级）
2. ``D:\\astock_trader``（Windows 且 D 盘存在时；本机数据盘）
3. ``~/.astock_trader``（兜底，非 Windows 或没有 D 盘时）

第 2 条只在 **D 盘根目录真实存在** 时生效，所以在 Linux/macOS 与 CI 上不会
凭空造出一个 ``D:\\`` 路径。
"""

from __future__ import annotations

import os

__all__ = ["resolve_project_dir", "project_dir", "project_path", "ENV_HOME"]

# 显式指定项目根的变量名
ENV_HOME = "ASTOCK_HOME"

_LEGACY_DIRNAME = ".astock_trader"
_PREFERRED_ROOT = "D:\\astock_trader"


def resolve_project_dir() -> str:
    """返回项目根目录（绝对路径）。不创建目录，只解析。"""
    override = os.environ.get(ENV_HOME, "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))

    preferred = os.path.abspath(_PREFERRED_ROOT)
    # 只在盘符根真实存在时才用它 —— 否则（含非 Windows）退回主目录。
    if os.path.isdir(os.path.dirname(preferred)):
        return preferred

    return os.path.join(os.path.expanduser("~"), _LEGACY_DIRNAME)


def project_dir() -> str:
    """:func:`resolve_project_dir` 的别名，供调用点读起来更顺。"""
    return resolve_project_dir()


def project_path(*parts: str) -> str:
    """在项目根下拼一个子路径。

    >>> project_path("reports")            # doctest: +SKIP
    'D:\\\\astock_trader\\\\reports'
    """
    return os.path.join(resolve_project_dir(), *parts)
