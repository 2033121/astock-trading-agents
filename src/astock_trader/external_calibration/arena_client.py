"""Headline Arena REST 客户端 — 只读接入，无凭据时优雅降级。

接入契约来源（2026-09 实测）
---------------------------
- 官方 OpenAPI 规范：``https://headlinearena.com/api/openapi.json``
- 公开读端点（**无需登录/凭据**）：
  - ``GET /eval/agents/{agent_id}/predictions``  预测历史（含机械结算结果）
  - ``GET /eval/agents/{agent_id}/calibration``  公开校准曲线
  - ``GET /eval/agents/{agent_id}/scorecard``    公开记分卡
- 需凭据端点：``POST /agent/auth/token``（client_credentials 换 access token）。

设计约束
--------
1. **无凭据必须优雅跳过而非报错。** 预测历史/校准曲线是公开端点，试点期零凭据即可
   跑通读侧；只有需要读取往季归档或未来提交预测时才需要 token。
2. **凭证纪律。** agent_id / client_secret 只从环境变量读取，绝不写入仓库或日志。
   本模块不提供任何把凭据落盘的方法。
3. **绝不抛异常。** 网络/鉴权/结构异常一律记录日志并返回 ``None``，
   调用方按「无外部校准数据」处理——与 :mod:`astock_trader.agents.utils.backtest_consumer`
   的「文件不存在时自动降级为无操作」保持同一姿态。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from typing import Any

from astock_trader.external_calibration.schema import (
    DEFAULT_BASE_URL,
    ENV_AGENT_ID,
    ENV_BASE_URL,
    ENV_CLIENT_SECRET,
    ENV_TOKEN,
    now_iso,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15
_PAGE_SIZE_MAX = 100
# 平台前置网关对缺少 User-Agent 的请求直接返回 403（2026-09 实机验证），
# 因此所有请求都带一个可识别的 UA，便于对面定位流量来源。
_USER_AGENT = "astock-trading-agents/external-calibration (+https://github.com/2033121/astock-trading-agents)"
# 提前 60 秒判定 token 过期，避免边界上用到刚失效的 token
_TOKEN_SAFETY_MARGIN = 60.0
_DEFAULT_EXPIRES_IN = 3600.0


class HeadlineArenaClient:
    """Headline Arena 只读客户端。

    Parameters
    ----------
    agent_id : str | None
        arena 上的 agent 标识。``None`` 时回落到环境变量 ``HEADLINE_ARENA_AGENT_ID``。
    client_secret : str | None
        换取 access token 用；``None`` 时回落 ``HEADLINE_ARENA_CLIENT_SECRET``。
        只用于内存中换取 token，不会被写盘。
    token : str | None
        预置 bearer token；``None`` 时回落 ``HEADLINE_ARENA_TOKEN``。
    base_url : str | None
        API 根地址，默认 ``https://headlinearena.com/api/v1``。
    timeout : int
        单次请求超时（秒）。
    session : Any | None
        注入的 HTTP 会话（需实现 ``request(method, url, **kwargs)``）。
        默认懒加载 ``requests.Session()``；测试用假会话替代即可离线运行。
    env : Mapping | None
        环境变量来源，默认 ``os.environ``；便于测试注入。
    """

    def __init__(
        self,
        agent_id: str | None = None,
        client_secret: str | None = None,
        token: str | None = None,
        base_url: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        session: Any | None = None,
        env: Any | None = None,
    ) -> None:
        env = os.environ if env is None else env
        self._agent_id = (agent_id if agent_id is not None else env.get(ENV_AGENT_ID, "") or "").strip()
        self._client_secret = (
            client_secret if client_secret is not None else env.get(ENV_CLIENT_SECRET, "") or ""
        ).strip()
        self._static_token = (token if token is not None else env.get(ENV_TOKEN, "") or "").strip()
        self._base_url = (base_url or env.get(ENV_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._session = session
        self._cached_token: str = ""
        self._cached_until: float = 0.0
        self._skip_logged = False

    # ─────────────────── 只读属性 ───────────────────

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def is_configured(self) -> bool:
        """是否具备最低可用配置（agent_id）。

        公开端点只需要 agent_id，因此没有 client_secret 也算可用。
        """
        return bool(self._agent_id)

    @property
    def has_credentials(self) -> bool:
        """是否具备换取 access token 的凭据（或预置 token）。"""
        return bool(self._static_token or (self._agent_id and self._client_secret))

    # ─────────────────── 公开读 API ───────────────────

    def fetch_predictions(
        self,
        *,
        since: str | None = None,
        limit: int = _PAGE_SIZE_MAX,
        offset: int = 0,
    ) -> dict[str, Any] | None:
        """拉取本 agent 的预测历史（含结算结果）的一页原始响应。

        Parameters
        ----------
        since : str | None
            ISO 8601 时间戳，只返回 ``created_at >= since`` 的记录（增量同步用）。
        limit : int
            每页条数，1–100。
        offset : int
            偏移量。

        Returns
        -------
        dict | None
            平台原始响应（``items`` / ``total`` / ``season_id`` …）；
            未配置或缺省失败时返回 ``None``。
        """
        if not self._guard_configured("fetch_predictions"):
            return None
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), _PAGE_SIZE_MAX)),
            "offset": max(0, int(offset)),
        }
        if since:
            params["since"] = since
        data = self._request("GET", f"/eval/agents/{self._agent_id}/predictions", params=params)
        if not isinstance(data, dict):
            return None
        return data

    def iter_predictions(self, *, since: str | None = None, page_size: int = _PAGE_SIZE_MAX) -> Iterator[dict]:
        """分页产出预测历史条目；任何一页失败即停止（不抛异常）。

        翻页上界由平台返回的 ``total`` 决定，且每页必须推进 offset，
        避免平台异常时死循环。
        """
        page_size = max(1, min(int(page_size), _PAGE_SIZE_MAX))
        offset = 0
        seen = 0
        while True:
            page = self.fetch_predictions(since=since, limit=page_size, offset=offset)
            if not page:
                return
            items = page.get("items") or []
            if not isinstance(items, list) or not items:
                return
            for item in items:
                if isinstance(item, dict):
                    seen += 1
                    yield item
            offset += len(items)
            total = page.get("total")
            if len(items) < page_size:
                return
            if isinstance(total, int) and seen >= total:
                return

    def fetch_calibration(self, *, include_btc: bool = False) -> dict[str, Any] | None:
        """拉取平台公开的校准曲线（分箱：平均置信度 vs 实测命中率）。"""
        if not self._guard_configured("fetch_calibration"):
            return None
        params: dict[str, Any] = {}
        if include_btc:
            params["include_btc"] = "true"
        data = self._request("GET", f"/eval/agents/{self._agent_id}/calibration", params=params)
        return data if isinstance(data, dict) else None

    def fetch_scorecard(self) -> dict[str, Any] | None:
        """拉取平台公开的记分卡（总分/排名/分位/趋势）。"""
        if not self._guard_configured("fetch_scorecard"):
            return None
        data = self._request("GET", f"/eval/agents/{self._agent_id}/scorecard")
        return data if isinstance(data, dict) else None

    # ─────────────────── 鉴权（可选） ───────────────────

    def access_token(self) -> str | None:
        """返回可用的 access token，无凭据时返回 ``None``。

        预置 token 优先；否则用 client_credentials 换取并在内存中缓存至过期。
        """
        if self._static_token:
            return self._static_token
        if not (self._agent_id and self._client_secret):
            return None
        if self._cached_token and time.monotonic() < self._cached_until:
            return self._cached_token

        payload = {
            "grant_type": "client_credentials",
            "agent_id": self._agent_id,
            "client_secret": self._client_secret,
        }
        data = self._request("POST", "/agent/auth/token", json_body=payload)
        if not isinstance(data, dict):
            return None
        token = data.get("access_token") or data.get("token")
        if not token:
            logger.warning("Headline Arena 鉴权响应中缺少 access_token，跳过凭据化请求。")
            return None
        expires_in = data.get("expires_in") or _DEFAULT_EXPIRES_IN
        try:
            ttl = float(expires_in)
        except (TypeError, ValueError):
            ttl = _DEFAULT_EXPIRES_IN
        self._cached_token = str(token)
        self._cached_until = time.monotonic() + max(ttl - _TOKEN_SAFETY_MARGIN, 1.0)
        logger.debug("Headline Arena access token 已获取，有效期 %.0fs。", ttl)
        return self._cached_token

    # ─────────────────── 内部 ───────────────────

    def _guard_configured(self, op: str) -> bool:
        """未配置时记一次日志并返回 ``False``（优雅跳过，不报错）。"""
        if self.is_configured:
            return True
        if not self._skip_logged:
            logger.info(
                "外部校准未配置 agent_id（环境变量 %s），%s 跳过——这是预期行为，不是错误。",
                ENV_AGENT_ID,
                op,
            )
            self._skip_logged = True
        return False

    def _session_or_none(self) -> Any | None:
        if self._session is not None:
            return self._session
        try:
            import requests
        except ImportError:  # pragma: no cover - requests 是本项目硬依赖
            logger.warning("未安装 requests，外部校准读侧不可用。")
            return None
        self._session = requests.Session()
        return self._session

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: bool = False,
    ) -> Any | None:
        """执行一次 HTTP 请求；任何失败都返回 ``None`` 而不抛异常。"""
        session = self._session_or_none()
        if session is None:
            return None

        url = f"{self._base_url}{path}"
        headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
        if auth:
            token = self.access_token()
            if not token:
                logger.warning("外部校准需要凭据但未取得 token，跳过 %s。", path)
                return None
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001 - 契约要求绝不向上抛
            logger.warning("外部校准请求失败（%s %s）：%s", method, path, exc)
            return None

        status = getattr(response, "status_code", 0)
        if status >= 400:
            if status in (401, 403):
                logger.warning("外部校准鉴权失败（%s %s -> %s），请检查环境变量凭据。", method, path, status)
            elif status == 404:
                logger.info("外部校准端点不存在或无数据（%s -> 404）。", path)
            else:
                logger.warning("外部校准请求返回异常状态 %s（%s）。", status, path)
            return None

        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001 - 响应体非 JSON 同样降级
            logger.warning("外部校准响应不是合法 JSON（%s）：%s", path, exc)
            return None


def default_client() -> HeadlineArenaClient:
    """按环境变量构造默认客户端（未配置时返回一个会优雅跳过的实例）。"""
    return HeadlineArenaClient()


__all__ = ["HeadlineArenaClient", "default_client", "now_iso"]
