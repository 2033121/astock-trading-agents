"""LLM 调用容错层 — 提供 Tenacity 指数退避重试 + 三态熔断器保护 + Headroom Token 压缩。

该模块包装 LangChain LLM 的 ``.invoke()`` 调用，为多智能体交易分析系统提供：
- **指数退避重试**：通过 Tenacity 实现，可配置最大重试次数、基础延迟和最大延迟。
- **三态熔断器**（CLOSED → OPEN → HALF_OPEN）：防止对持续故障的 LLM 服务反复请求。
- **Headroom Token 压缩**：在 LLM 调用前压缩消息，典型节省 60-95% Token。
- **结构化日志**：记录智能体名称、估算 token 数、耗时、压缩率等关键指标。

设计参考 webnovel-studio ``base.py``，针对 A 股交易分析场景独立实现。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from tenacity import (
    Retrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger("astock_trader.llm_clients.resilience")

# ---------------------------------------------------------------------------
# Headroom integration — config keys
# ---------------------------------------------------------------------------

# 可通过 default_config 或环境变量覆盖
_ENABLE_HEADROOM: bool = False       # 默认关闭，需主动开启
_HEADROOM_MIN_TOKENS: int = 500      # 少于该 token 数不压缩（小消息没必要）
_HEADROOM_LOGGER = logging.getLogger("astock_trader.llm_clients.headroom")


def configure_headroom(*, enable: bool | None = None, min_tokens: int | None = None) -> None:
    """运行时配置 Headroom 压缩参数。

    Parameters
    ----------
    enable : bool | None
        是否启用 Headroom 压缩。``None`` 表示保持当前值。
    min_tokens : int | None
        最小 Token 数阈值，低于此值跳过压缩。
    """
    global _ENABLE_HEADROOM, _HEADROOM_MIN_TOKENS
    if enable is not None:
        _ENABLE_HEADROOM = enable
        _HEADROOM_LOGGER.info("Headroom compression %s", "ENABLED" if enable else "DISABLED")
    if min_tokens is not None:
        _HEADROOM_MIN_TOKENS = min_tokens


def _msg_to_dict(msg: Any) -> dict:
    """将 LangChain 消息或任意消息格式转为 OpenAI 兼容的 dict。"""
    if isinstance(msg, dict):
        return msg
    # LangChain BaseMessage 对象
    if hasattr(msg, "type") and hasattr(msg, "content"):
        role = msg.type
        # LangChain 的 type 是 "human" / "ai" / "system" 等
        # OpenAI 用的是 "user" / "assistant" / "system"
        role_map = {"human": "user", "ai": "assistant"}
        return {"role": role_map.get(role, role), "content": msg.content}
    # 兜底
    return {"role": "user", "content": str(msg)}


def _compress_messages(messages: list, agent_name: str) -> list:
    """尝试用 Headroom 压缩消息列表；失败时返回原始消息。

    压缩的对象是 OpenAI 兼容格式的 dict 列表，压缩后也是同样的格式，
    可以直接传给 LangChain ``llm.invoke()``。
    """
    if not _ENABLE_HEADROOM:
        return messages

    # 快速 token 估算（约 4 char/token），小额消息跳过
    est_tokens = sum(max(1, len(str(m)) // 4) for m in messages)
    if est_tokens < _HEADROOM_MIN_TOKENS:
        _HEADROOM_LOGGER.debug(
            "[%s] Skipping headroom: est. %d tokens < min %d",
            agent_name, est_tokens, _HEADROOM_MIN_TOKENS,
        )
        return messages

    try:
        from headroom import compress as headroom_compress

        # 统一转为 dict 格式
        dict_msgs = [_msg_to_dict(m) for m in messages]
        result = headroom_compress(dict_msgs)

        compressed = result.messages
        saved = getattr(result, "tokens_saved", 0)
        ratio = getattr(result, "compression_ratio", 0.0)

        if saved > 0:
            _HEADROOM_LOGGER.info(
                "[%s] Headroom compressed: saved ~%d tokens (ratio: %.2f)",
                agent_name, saved, ratio,
            )
        else:
            _HEADROOM_LOGGER.debug(
                "[%s] Headroom: no compression gain (est. %d tokens)",
                agent_name, est_tokens,
            )

        return compressed
    except Exception as exc:
        _HEADROOM_LOGGER.warning(
            "[%s] Headroom compression failed (%s: %s), using original messages",
            agent_name, type(exc).__name__, exc,
        )
        return messages


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class CircuitBreakerOpen(Exception):
    """熔断器处于 OPEN 状态时抛出，表示当前不应发起请求。

    Attributes
    ----------
    agent_name : str
        触发熔断的智能体名称。
    remaining_cooldown : float
        距离熔断器冷却窗口结束还剩多少秒。
    """

    def __init__(self, agent_name: str, remaining_cooldown: float) -> None:
        self.agent_name = agent_name
        self.remaining_cooldown = remaining_cooldown
        super().__init__(
            f"Circuit breaker OPEN for {agent_name!r}, "
            f"retry after {remaining_cooldown:.1f}s"
        )


# ---------------------------------------------------------------------------
# Retryable exception detection (no hard imports of openai / httpx)
# ---------------------------------------------------------------------------

# Class names considered retryable, matched against the MRO chain.
_RETRYABLE_NAMES: frozenset[str] = frozenset({
    # openai SDK
    "APIError",
    "RateLimitError",
    "APITimeoutError",
    "APIConnectionError",
    "InternalServerError",
    "ServiceUnavailableError",
    # langchain
    "OutputParserException",
    # stdlib
    "ConnectionError",
    "TimeoutError",
    "TimeoutException",
    # httpx
    "ConnectError",
    "ReadTimeout",
    "WriteTimeout",
    "PoolTimeout",
})

# Substrings checked against ``str(exc)`` (lower-cased).
_RETRYABLE_SUBSTRINGS: tuple[str, ...] = (
    "rate limit",
    "timeout",
    "connection",
)


def _is_retryable(exc: BaseException) -> bool:
    """Return ``True`` if *exc* is considered transient and worth retrying.

    The check walks the exception's MRO class names (no direct import of
    ``openai`` / ``httpx``) and also inspects the string representation
    for well-known keywords.
    """
    # Walk MRO class names
    for cls in type(exc).__mro__:
        if cls.__name__ in _RETRYABLE_NAMES:
            return True

    # Fallback: check string representation
    msg = str(exc).lower()
    return any(sub in msg for sub in _RETRYABLE_SUBSTRINGS)


# ---------------------------------------------------------------------------
# Circuit breaker (three-state)
# ---------------------------------------------------------------------------


class _CircuitBreaker:
    """三态熔断器：CLOSED → OPEN → HALF_OPEN → CLOSED。

    Parameters
    ----------
    failure_threshold : int
        连续失败多少次后触发熔断，默认 5。
    recovery_timeout : float
        熔断后冷却窗口时长（秒），默认 30.0。
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._consecutive_failures: int = 0
        self._state: str = self.CLOSED
        self._opened_at: float = 0.0

    # -- state property with auto-transition ----------------------------------

    @property
    def state(self) -> str:
        """返回当前状态；若冷却窗口已过，自动从 OPEN 转为 HALF_OPEN。"""
        if self._state == self.OPEN:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.recovery_timeout:
                self._state = self.HALF_OPEN
                logger.info(
                    "Circuit breaker transitioning OPEN -> HALF_OPEN (cooldown %.1fs elapsed)",
                    elapsed,
                )
        return self._state

    # -- public API -----------------------------------------------------------

    def allow_request(self) -> bool:
        """是否允许发起请求（CLOSED 和 HALF_OPEN 允许）。"""
        s = self.state
        return s in (self.CLOSED, self.HALF_OPEN)

    def remaining_cooldown(self) -> float:
        """返回距离冷却窗口结束的剩余秒数；非 OPEN 状态返回 0.0。"""
        if self._state == self.OPEN:
            elapsed = time.monotonic() - self._opened_at
            return max(0.0, self.recovery_timeout - elapsed)
        return 0.0

    def record_success(self) -> None:
        """记录成功：重置失败计数并回到 CLOSED 状态。"""
        if self._state == self.HALF_OPEN:
            logger.info("Circuit breaker HALF_OPEN -> CLOSED (probe succeeded)")
        self._consecutive_failures = 0
        self._state = self.CLOSED

    def record_failure(self) -> None:
        """记录失败：累计失败次数，达到阈值则熔断。"""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._state = self.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "Circuit breaker -> OPEN after %d consecutive failures (cooldown %.1fs)",
                self._consecutive_failures,
                self.recovery_timeout,
            )


# ---------------------------------------------------------------------------
# Tenacity before_sleep hook
# ---------------------------------------------------------------------------


def _log_retry(retry_state: RetryCallState) -> None:
    """Tenacity ``before_sleep`` 回调：记录重试日志。"""
    attempt = retry_state.attempt_number
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    wait = retry_state.upcoming_sleep if hasattr(retry_state, "upcoming_sleep") else "N/A"
    logger.warning(
        "Retrying LLM call (attempt %d) — last error: %s — next wait: %s",
        attempt,
        exc,
        f"{wait:.1f}s" if isinstance(wait, (int, float)) else wait,
    )


# ---------------------------------------------------------------------------
# safe_invoke — functional entry point
# ---------------------------------------------------------------------------


def safe_invoke(
    llm: Any,
    messages: Any,
    agent_name: str,
    *,
    max_retries: int = 3,
    base_delay: int = 4,
    max_delay: int = 60,
    circuit_breaker: _CircuitBreaker | None = None,
) -> str:
    """包装 ``llm.invoke(messages)`` 并附加熔断器 + 指数退避重试。

    Parameters
    ----------
    llm : Any
        LangChain LLM 实例（如 ``ChatOpenAI``），必须有 ``.invoke()`` 方法。
    messages : Any
        传给 ``.invoke()`` 的消息列表。
    agent_name : str
        调用方智能体名称，用于日志和熔断器标识。
    max_retries : int
        最大重试次数，默认 3。
    base_delay : int
        指数退避基础延迟（秒），默认 4。
    max_delay : int
        指数退避最大延迟（秒），默认 60。
    circuit_breaker : _CircuitBreaker | None
        可选的熔断器实例。若为 ``None`` 则跳过熔断检查。

    Returns
    -------
    str
        ``response.content`` 字符串。

    Raises
    ------
    CircuitBreakerOpen
        熔断器处于 OPEN 状态时立即抛出。
    """
    # -- circuit breaker gate -------------------------------------------------
    if circuit_breaker is not None and not circuit_breaker.allow_request():
        raise CircuitBreakerOpen(
            agent_name=agent_name,
            remaining_cooldown=circuit_breaker.remaining_cooldown(),
        )

    # -- Headroom compression -------------------------------------------------
    compressed_msgs = _compress_messages(messages, agent_name)

    # -- estimate tokens for logging -----------------------------------------
    est_tokens = max(1, len(str(compressed_msgs)) // 4)
    t0 = time.monotonic()

    # -- tenacity retry loop --------------------------------------------------
    for attempt in Retrying(
        stop=stop_after_attempt(max_retries + 1),  # +1 because first call counts
        wait=wait_exponential(multiplier=base_delay, max=max_delay),
        retry=retry_if_exception(_is_retryable),
        before_sleep=_log_retry,
        reraise=True,
    ):
        with attempt:
            logger.debug(
                "[%s] Invoking LLM (est. ~%d tokens)", agent_name, est_tokens
            )
            response = llm.invoke(compressed_msgs)

    # If we reach here, the call succeeded.
    elapsed = time.monotonic() - t0
    content: str = response.content if hasattr(response, "content") else str(response)
    logger.info(
        "[%s] LLM call succeeded — est. ~%d tokens, %.2fs elapsed",
        agent_name,
        est_tokens,
        elapsed,
    )

    # -- record success on circuit breaker -----------------------------------
    if circuit_breaker is not None:
        circuit_breaker.record_success()

    return content


# ---------------------------------------------------------------------------
# ResilientInvoker — stateful convenience wrapper
# ---------------------------------------------------------------------------


class ResilientInvoker:
    """持有配置和熔断器注册表的容错调用器。

    ``setup.py`` 中的各节点共享同一个实例，通过 ``agent_name`` 区分不同的
    熔断器。首次遇到某 ``agent_name`` 时自动创建对应的 ``_CircuitBreaker``。

    Parameters
    ----------
    max_retries : int
        每次调用的最大重试次数，默认 3。
    base_delay : int
        指数退避基础延迟（秒），默认 4。
    max_delay : int
        指数退避最大延迟（秒），默认 60。
    cb_threshold : int
        熔断器连续失败阈值，默认 5。
    cb_cooldown : float
        熔断器冷却窗口时长（秒），默认 30。

    Examples
    --------
    >>> invoker = ResilientInvoker()
    >>> content = invoker.invoke(llm, messages, agent_name="fund_manager")
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: int = 4,
        max_delay: int = 60,
        cb_threshold: int = 5,
        cb_cooldown: float = 30.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.cb_threshold = cb_threshold
        self.cb_cooldown = cb_cooldown
        self._breakers: dict[str, _CircuitBreaker] = {}

    def _get_breaker(self, agent_name: str) -> _CircuitBreaker:
        """获取或创建指定智能体的熔断器。"""
        if agent_name not in self._breakers:
            self._breakers[agent_name] = _CircuitBreaker(
                failure_threshold=self.cb_threshold,
                recovery_timeout=self.cb_cooldown,
            )
            logger.debug("Created circuit breaker for %r", agent_name)
        return self._breakers[agent_name]

    def invoke(self, llm: Any, messages: Any, agent_name: str) -> str:
        """带重试和熔断保护的 LLM 调用。返回 ``response.content`` 字符串。

        Parameters
        ----------
        llm : Any
            LangChain LLM 实例。
        messages : Any
            传给 ``.invoke()`` 的消息列表。
        agent_name : str
            调用方智能体名称。

        Returns
        -------
        str
            模型返回的文本内容。
        """
        breaker = self._get_breaker(agent_name)

        try:
            return safe_invoke(
                llm,
                messages,
                agent_name,
                max_retries=self.max_retries,
                base_delay=self.base_delay,
                max_delay=self.max_delay,
                circuit_breaker=breaker,
            )
        except CircuitBreakerOpen:
            # Breaker is already OPEN — no actual LLM call was attempted,
            # so do NOT record a failure; just propagate.
            raise
        except Exception:
            # All retries exhausted or non-retryable error — record failure
            # so the breaker can eventually open after enough consecutive fails.
            breaker.record_failure()
            raise
