"""Response-level semantic cache for LLM nodes (Token strategy 3).

Purpose-built for repeated analyses of the *same stock on the same day*:
analyst-researcher/manager prompts then differ only in whitespace and minor
wording, while outputs are otherwise identical.  The cache sits at node-call
level (`GraphSetup._safe_invoke`), never below the LLM client, so tool-based
ReAct analysts stay untouched.

Safety policy
-------------
- **Off by default**: quality-first; enable via ``enable_semantic_cache``.
- Exact-key match on a *normalized* prompt (whitespace/punct folded) is the
  primary route; a conservative `difflib.SequenceMatcher` similarity pass
  (default threshold 0.92) may reuse a near-identical past response within
  the TTL window.
- TTL (default 60 min) guarantees fresh data windows; entries are evicted
  LRU when ``max_entries`` is exceeded.
- Never persists to disk — per-process cache only.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import logging
import re
import threading
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[，。！？；：（）“”‘’、,\.!:;()\[\]{}\"'`*_#>—-]+")


def normalize_prompt(text: str) -> str:
    """Fold whitespace and CJK/ASCII punctuation for stable cache keys."""
    text = _WS_RE.sub("", text)
    return _PUNCT_RE.sub("", text)


def _messages_to_text(messages: Any) -> str:
    """Render LangChain-style messages (tuples / objects) into one string."""
    parts: list[str] = []
    for m in messages:
        if isinstance(m, tuple):
            parts.append(str(m[0]))
            parts.append(str(m[-1]))
        else:
            content = getattr(m, "content", None)
            if content is None:
                try:
                    content = m.get("content", "")
                except AttributeError:
                    content = str(m)
            parts.append(str(getattr(m, "type", "")))
            parts.append(str(content))
    return "\n".join(parts)


class SemanticCache:
    """TTL + LRU response cache with optional near-duplicate matching."""

    def __init__(
        self,
        *,
        ttl_minutes: float = 60,
        max_entries: int = 256,
        similarity_threshold: float = 0.92,
    ) -> None:
        self.ttl_seconds = max(ttl_minutes, 0.0) * 60
        self.max_entries = max(max_entries, 1)
        self.similarity_threshold = similarity_threshold
        self._lock = threading.Lock()
        # key -> (model, agent_name, expires_at, normalized_text, payload)
        self._store: OrderedDict[str, tuple[str, str, float, str, str]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    # ------------------------------------------------------------------
    # key management
    # ------------------------------------------------------------------

    @staticmethod
    def make_key(model: str, agent_name: str, messages: Any) -> str:
        text = _messages_to_text(messages)
        norm = normalize_prompt(text)
        digest = hashlib.sha256(f"{model}\x1f{agent_name}\x1f{norm}".encode()).hexdigest()
        return f"{digest}\x1f{len(norm)}"

    def _purge_expired(self, now: float) -> None:
        stale = [k for k, (_, _, exp, _, _) in self._store.items() if exp <= now]
        for k in stale:
            self._store.pop(k, None)

    # ------------------------------------------------------------------
    # lookup / store
    # ------------------------------------------------------------------

    def get(self, model: str, agent_name: str, messages: Any) -> tuple[str, str] | None:
        """Return ``(payload, kind)`` where kind is "exact" | "similar", or None."""
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            key = self.make_key(model, agent_name, messages)
            hit = self._store.get(key)
            if hit is not None:
                model_, agent_, exp, _norm, payload = hit
                self._move_to_front(key)
                self.hits += 1
                return payload, "exact"

            # similarity pass (cheap: bounded store, no embeddings)
            if self.similarity_threshold < 1.0:
                norm = _messages_to_text(messages)
                for k, (m_, a_, exp, cached_norm, payload_) in self._store.items():
                    if m_ != model or a_ != agent_name:
                        continue
                    ratio = difflib.SequenceMatcher(None, norm, cached_norm).quick_ratio()
                    if ratio < self.similarity_threshold:
                        continue
                    if difflib.SequenceMatcher(None, norm, cached_norm).ratio() >= self.similarity_threshold:
                        self.hits += 1
                        self._move_to_front(k)
                        logger.info(
                            "Semantic cache near-hit for %s (similarity >= %.2f)",
                            agent_name,
                            self.similarity_threshold,
                        )
                        return payload_, "similar"
            self.misses += 1
            return None

    def put(self, model: str, agent_name: str, messages: Any, payload: str) -> None:
        if self.ttl_seconds <= 0:
            return
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            key = self.make_key(model, agent_name, messages)
            while len(self._store) >= self.max_entries:
                self._store.popitem(last=False)
            self._store[key] = (
                model,
                agent_name,
                now + self.ttl_seconds,
                _messages_to_text(messages),
                payload,
            )

    def _move_to_front(self, key: str) -> None:
        with contextlib.suppress(KeyError):
            self._store.move_to_end(key)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired(time.time())
            return len(self._store)


def cached_invoke(
    llm: Any,
    messages: Any,
    agent_name: str,
    cache: SemanticCache | None,
    model_name: str = "",
) -> str:
    """Invoke ``llm`` via ``cache`` if configured; otherwise straight call.

    The LLM is a LangChain chat model or a plain object exposing ``invoke``;
    the returned ``.content`` string is cached.
    """
    if cache is None:
        response = llm.invoke(messages)
        return response.content if hasattr(response, "content") else str(response)

    model_name = (
        model_name or getattr(getattr(llm, "model_name", None), "model", "") or str(getattr(llm, "model_name", ""))
    )
    found = cache.get(model_name, agent_name, messages)
    if found is not None:
        payload, kind = found
        logger.info("Semantic cache %s hit for %s", kind, agent_name)
        return payload

    response = llm.invoke(messages)
    content = response.content if hasattr(response, "content") else str(response)
    cache.put(model_name, agent_name, messages, content)
    return content


__all__ = ["SemanticCache", "cached_invoke", "normalize_prompt"]
