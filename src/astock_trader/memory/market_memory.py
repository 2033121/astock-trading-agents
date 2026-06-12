"""Vector memory for historical trading analysis retrieval.

Indexes past analysis results (analyst reports, debate outcomes, final decisions)
so that agents can retrieve semantically similar historical cases beyond the
simple "last N decisions" window.

Uses a lightweight TF-IDF + bigram backend by default (pure Python, zero deps).
ChromaDB is used automatically when installed for embedding-level semantic search.

Usage::

    mem = MarketMemory()
    mem.index_analysis("600519", "2026-06-01", "贵州茅台分析报告...", rating="买入")
    records = mem.search("白酒行业龙头估值", top_k=3)
"""

from __future__ import annotations

import json
import logging
import math
import os
import pickle
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import chromadb  # type: ignore[import-untyped]
    _HAS_CHROMA = True
except ImportError:
    _HAS_CHROMA = False


# ======================================================================
# Data class
# ======================================================================


@dataclass
class AnalysisRecord:
    """A single indexed analysis segment with metadata."""
    ticker: str
    date: str
    chunk_index: int
    content: str
    rating: str = ""
    keywords: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.ticker}_{self.date}#{self.chunk_index}"


# ======================================================================
# Text segmentation helpers
# ======================================================================

_SPLIT_RE = re.compile(r"\n\s*###?\s+|\n---+\n|\n\*{3,}\n")
_KEYWORD_RE = re.compile(r"[\u4e00-\u9fff]{2,6}|[A-Za-z]{3,}")

_MIN_CHUNK_CHARS = 300
_MAX_CHUNK_CHARS = 1200

# Financial stopwords (Chinese)
_FINANCE_STOPWORDS = {
    "分析", "报告", "市场", "公司", "股票", "投资", "建议",
    "数据", "指标", "趋势", "情况", "方面", "问题", "结果",
    "目前", "当前", "近期", "未来", "预计", "可能", "可以",
    "但是", "然而", "同时", "此外", "因此", "所以", "如果",
}


def _split_analysis_text(text: str) -> list[str]:
    """Split an analysis document into topic-level segments."""
    raw_parts = _SPLIT_RE.split(text)
    segments: list[str] = []
    buffer = ""

    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        if len(buffer) + len(part) + 1 <= _MAX_CHUNK_CHARS:
            buffer = f"{buffer}\n\n{part}".strip() if buffer else part
        else:
            if buffer:
                segments.append(buffer)
            if len(part) > _MAX_CHUNK_CHARS:
                paragraphs = part.split("\n")
                buffer = ""
                for para in paragraphs:
                    para = para.strip()
                    if not para:
                        continue
                    if len(buffer) + len(para) + 1 <= _MAX_CHUNK_CHARS:
                        buffer = f"{buffer}\n{para}".strip() if buffer else para
                    else:
                        if buffer:
                            segments.append(buffer)
                        buffer = para
            else:
                buffer = part

    if buffer and len(buffer) >= _MIN_CHUNK_CHARS:
        segments.append(buffer)
    elif buffer and segments:
        segments[-1] = f"{segments[-1]}\n\n{buffer}".strip()
    elif buffer:
        segments.append(buffer)

    return segments


def _extract_keywords(text: str) -> list[str]:
    """Extract likely stock/industry keywords from text."""
    candidates = _KEYWORD_RE.findall(text)
    counts = Counter(c for c in candidates if c not in _FINANCE_STOPWORDS and len(c) >= 2)
    return [kw for kw, _ in counts.most_common(15)]


# ======================================================================
# TF-IDF backend (pure Python, no external dependencies)
# ======================================================================


class _TfIdfIndex:
    """Minimal TF-IDF index using character bigrams as tokens."""

    def __init__(self) -> None:
        self.docs: list[dict] = []
        self.df: Counter = Counter()
        self._n: int = 0

    def add(self, record: AnalysisRecord) -> None:
        tokens = self._tokenise(record.content)
        self.docs.append({"record": record, "tokens": tokens})
        unique_tokens = set(tokens.keys())
        for t in unique_tokens:
            self.df[t] += 1
        self._n += 1

    def search(self, query: str, top_k: int = 5) -> list[AnalysisRecord]:
        if not self.docs:
            return []

        query_tokens = self._tokenise(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, int]] = []
        for idx, doc in enumerate(self.docs):
            score = self._cosine_sim(query_tokens, doc["tokens"])
            if score > 0:
                scored.append((score, idx))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[AnalysisRecord] = []
        for score, idx in scored[:top_k]:
            record = self.docs[idx]["record"]
            record.score = round(score, 4)
            results.append(record)
        return results

    @staticmethod
    def _tokenise(text: str) -> Counter:
        """Character bigram tokenisation for Chinese financial text."""
        chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]
        bigrams = [f"{chars[i]}{chars[i+1]}" for i in range(len(chars) - 1)]
        # Also include English words
        eng_words = re.findall(r"[A-Za-z]{3,}", text)
        tokens: list[str] = chars + bigrams + bigrams + eng_words
        return Counter(tokens)

    def _cosine_sim(self, a: Counter, b: Counter) -> float:
        """TF-IDF weighted cosine similarity."""
        if not a or not b:
            return 0.0

        common_keys = set(a.keys()) & set(b.keys())
        if not common_keys:
            return 0.0

        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0

        for key in set(a.keys()) | set(b.keys()):
            idf = self._idf(key)
            wa = a.get(key, 0) * idf
            wb = b.get(key, 0) * idf
            dot += wa * wb
            norm_a += wa * wa
            norm_b += wb * wb

        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    def _idf(self, token: str) -> float:
        """Inverse document frequency with smoothing."""
        df = self.df.get(token, 0)
        if df == 0:
            return 0.0
        return math.log((self._n + 1) / (df + 1)) + 1


# ======================================================================
# MarketMemory — public API
# ======================================================================


class MarketMemory:
    """Semantic memory store for historical trading analyses.

    Parameters
    ----------
    backend : str
        ``"auto"`` (default), ``"chroma"``, or ``"tfidf"``.
    persist_dir : str | Path | None
        Directory for persisting the index. ``None`` = in-memory only.
    """

    def __init__(
        self,
        backend: str = "auto",
        persist_dir: str | Path | None = None,
    ) -> None:
        self.persist_dir = Path(persist_dir) if persist_dir else None

        if backend == "chroma" or (backend == "auto" and _HAS_CHROMA):
            self._backend = "chroma"
            self._init_chroma()
        else:
            self._backend = "tfidf"
            self._init_tfidf()

        self._analysis_texts: dict[str, str] = {}

        logger.info(
            "MarketMemory initialised (backend=%s, persist=%s)",
            self._backend, self.persist_dir or "in-memory",
        )

    # -- Public API --

    def index_analysis(
        self,
        ticker: str,
        date: str,
        content: str,
        rating: str = "",
    ) -> int:
        """Segment and index an analysis result.

        Parameters
        ----------
        ticker : str
            Stock code (e.g. "600519").
        date : str
            Analysis date (YYYY-MM-DD).
        content : str
            Full analysis text (may include multiple reports).
        rating : str
            Final rating (e.g. "买入").

        Returns
        -------
        int
            Number of chunks created.
        """
        label = f"{ticker}_{date}"
        self._analysis_texts[label] = content

        segments = _split_analysis_text(content)
        if not segments:
            logger.warning("index_analysis: no segments from %s", label)
            return 0

        keywords = _extract_keywords(content)

        for i, seg in enumerate(segments):
            record = AnalysisRecord(
                ticker=ticker,
                date=date,
                chunk_index=i,
                content=seg,
                rating=rating,
                keywords=list(set(_extract_keywords(seg)) | set(keywords[:10])),
            )
            self._add_record(record)

        logger.info("Indexed %s: %d segments (rating=%s)", label, len(segments), rating)
        return len(segments)

    def search(self, query: str, top_k: int = 3) -> list[AnalysisRecord]:
        """Semantic search for analysis records relevant to *query*."""
        return self._search(query, top_k=top_k)

    def search_by_ticker(self, ticker: str, top_k: int = 3) -> list[AnalysisRecord]:
        """Search for records about a specific ticker.

        First attempts TF-IDF semantic search, then falls back to
        direct metadata scan for exact ticker matches.
        """
        # Try semantic search first
        results = self._search(ticker, top_k=top_k * 3)
        filtered = [r for r in results if r.ticker == ticker or ticker in r.content]

        if len(filtered) < top_k:
            # Fallback: scan all records for exact ticker match
            seen = {r.label for r in filtered}
            for rec in self._all_records:
                if rec.ticker == ticker and rec.label not in seen:
                    filtered.append(rec)
                    seen.add(rec.label)
                    if len(filtered) >= top_k:
                        break

        return filtered[:top_k]

    def get_analysis_context(self, ticker: str, date: str) -> str:
        """Get the full text of a previously indexed analysis."""
        label = f"{ticker}_{date}"
        return self._analysis_texts.get(label, "")

    def format_for_prompt(
        self,
        records: list[AnalysisRecord],
        max_chars: int = 2000,
    ) -> str:
        """Format retrieved records into a prompt-injectable string.

        Parameters
        ----------
        records : list[AnalysisRecord]
            Records from a search query.
        max_chars : int
            Maximum total characters for the formatted output.

        Returns
        -------
        str
            Formatted text block, or empty string if no records.
        """
        if not records:
            return ""

        lines = ["## 历史分析参考"]
        total = 0

        for rec in records:
            header = f"\n### {rec.ticker} ({rec.date}) — {rec.rating}"
            # Truncate content to fit budget
            remaining = max_chars - total - len(header) - 20
            if remaining <= 50:
                break
            content = rec.content[:remaining]
            entry = f"{header}\n{content}"
            lines.append(entry)
            total += len(entry)

        return "\n".join(lines) if len(lines) > 1 else ""

    def clear(self) -> None:
        """Clear all indexed data."""
        if self._backend == "chroma":
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                "market_memory"
            )
            ids = self._chroma_collection.get()["ids"]
            if ids:
                self._chroma_collection.delete(ids=ids)
        else:
            self._tfidf_index = _TfIdfIndex()
            self._all_records = []
        self._analysis_texts.clear()

    def save(self, path: str | Path | None = None) -> None:
        """Persist the current index to disk."""
        save_dir = Path(path) if path else self.persist_dir
        if not save_dir:
            return

        os.makedirs(save_dir, exist_ok=True)

        if self._backend == "chroma":
            pass  # ChromaDB persists automatically
        else:
            index_path = save_dir / "tfidf_index.pkl"
            with open(index_path, "wb") as f:
                pickle.dump(self._tfidf_index, f)
            records_path = save_dir / "all_records.json"
            data = [
                {"ticker": r.ticker, "date": r.date, "chunk_index": r.chunk_index,
                 "content": r.content, "rating": r.rating, "keywords": r.keywords}
                for r in self._all_records
            ]
            with open(records_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

        texts_path = save_dir / "analysis_texts.json"
        with open(texts_path, "w", encoding="utf-8") as f:
            json.dump(self._analysis_texts, f, ensure_ascii=False)

    def load(self, path: str | Path | None = None) -> None:
        """Load a previously persisted index from disk."""
        load_dir = Path(path) if path else self.persist_dir
        if not load_dir or not load_dir.is_dir():
            return

        if self._backend == "chroma":
            pass  # ChromaDB loads from persist_directory automatically
        else:
            index_path = load_dir / "tfidf_index.pkl"
            if index_path.is_file():
                with open(index_path, "rb") as f:
                    self._tfidf_index = pickle.load(f)
            records_path = load_dir / "all_records.json"
            if records_path.is_file():
                with open(records_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._all_records = [
                    AnalysisRecord(
                        ticker=d["ticker"], date=d["date"],
                        chunk_index=d["chunk_index"],
                        content=d["content"], rating=d.get("rating", ""),
                        keywords=d.get("keywords", []),
                    )
                    for d in data
                ]

        texts_path = load_dir / "analysis_texts.json"
        if texts_path.is_file():
            with open(texts_path, "r", encoding="utf-8") as f:
                self._analysis_texts = json.load(f)

    @property
    def record_count(self) -> int:
        if self._backend == "chroma":
            return self._chroma_collection.count()
        return len(self._all_records)

    # -- Backend init --

    def _init_chroma(self) -> None:
        persist = str(self.persist_dir) if self.persist_dir else None
        self._chroma_client = chromadb.PersistentClient(
            path=persist or "./.chroma_market"
        )
        self._chroma_collection = self._chroma_client.get_or_create_collection(
            "market_memory",
            metadata={"description": "Historical trading analysis semantic index"},
        )
        self._all_records: list[AnalysisRecord] = []

    def _init_tfidf(self) -> None:
        self._tfidf_index = _TfIdfIndex()
        self._all_records: list[AnalysisRecord] = []

    # -- Backend operations --

    def _add_record(self, record: AnalysisRecord) -> None:
        if self._backend == "chroma":
            doc_id = record.label
            self._chroma_collection.add(
                documents=[record.content],
                metadatas=[{
                    "ticker": record.ticker, "date": record.date,
                    "chunk_index": record.chunk_index,
                    "rating": record.rating,
                    "keywords": ",".join(record.keywords),
                }],
                ids=[doc_id],
            )
        else:
            self._tfidf_index.add(record)
        self._all_records.append(record)

    def _search(self, query: str, top_k: int = 5) -> list[AnalysisRecord]:
        if self._backend == "chroma":
            if self._chroma_collection.count() == 0:
                return []
            results = self._chroma_collection.query(
                query_texts=[query],
                n_results=min(top_k, self._chroma_collection.count()),
            )
            records: list[AnalysisRecord] = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results["metadatas"] else {}
                    dist = results["distances"][0][i] if results["distances"] else 0
                    kw_str = meta.get("keywords", "")
                    records.append(AnalysisRecord(
                        ticker=meta.get("ticker", ""),
                        date=meta.get("date", ""),
                        chunk_index=int(meta.get("chunk_index", 0)),
                        content=doc,
                        rating=meta.get("rating", ""),
                        keywords=kw_str.split(",") if kw_str else [],
                        score=round(1.0 - dist, 4),
                    ))
            return records
        else:
            return self._tfidf_index.search(query, top_k=top_k)
