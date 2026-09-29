"""向量记忆检索的时间点门控。

``MarketMemory.search`` 此前完全不看日期：一次 ``--date 2025-06-01`` 的历史分析
会把索引里「2026 年才写下的分析报告」按语义相似度捞出来注入 prompt —— 这是最
隐蔽的一类前视偏差，因为检索结果看起来只是「相似的历史案例」。

现在检索接受 ``as_of``：只返回 ``date <= as_of`` 的记录。TF-IDF 后端在排序前
过滤候选；chroma 后端下发 ``where`` 过滤条件，并在返回后再兜底过一遍（后端忽略
或支持不了该条件时，宁可少返回也不能放行未来记录）。
"""

import pytest

from astock_trader.memory.market_memory import MarketMemory

_QUERY = "白酒 龙头 估值 分析"


@pytest.fixture
def memory():
    """纯 Python TF-IDF 后端，无外部依赖。"""
    mem = MarketMemory(backend="tfidf", persist_dir=None)
    mem.index_analysis("600519", "2025-05-01", "白酒龙头的估值分析与渠道库存情况。" * 12, rating="增持")
    mem.index_analysis("600519", "2026-08-01", "白酒龙头的估值分析与渠道库存情况。" * 12, rating="买入")
    return mem


class TestTfIdfGating:
    """TF-IDF 后端的日期门控。"""

    def test_no_as_of_returns_everything(self, memory):
        """实时运行不过滤 —— 行为与改动前一致。"""
        dates = {r.date for r in memory.search(_QUERY, top_k=10)}
        assert dates == {"2025-05-01", "2026-08-01"}

    def test_as_of_excludes_future_records(self, memory):
        results = memory.search(_QUERY, top_k=10, as_of="2025-06-01")
        assert [r.date for r in results] == ["2025-05-01"]

    def test_as_of_on_the_record_date_is_inclusive(self, memory):
        results = memory.search(_QUERY, top_k=10, as_of="2025-05-01")
        assert [r.date for r in results] == ["2025-05-01"]

    def test_as_of_before_any_record_returns_empty(self, memory):
        assert memory.search(_QUERY, top_k=10, as_of="2025-04-30") == []

    def test_filters_candidates_before_ranking(self, memory):
        """未来记录被剔除后，top_k 仍然由历史记录填满，而不是返回空。"""
        results = memory.search(_QUERY, top_k=1, as_of="2025-06-01")
        assert len(results) == 1
        assert results[0].date == "2025-05-01"

    def test_unparseable_record_date_is_excluded(self, memory):
        memory.index_analysis("000001", "日期不明", "平安银行的零售业务转型分析。" * 12)
        results = memory.search(_QUERY, top_k=10, as_of="2025-06-01")
        assert all(r.date != "日期不明" for r in results)


class TestSearchByTickerGating:
    """按标的检索同样受门控（含直接扫元数据的那条兜底路径）。"""

    def test_metadata_fallback_respects_as_of(self, memory):
        results = memory.search_by_ticker("600519", top_k=10, as_of="2025-06-01")
        assert results
        assert all(r.date == "2025-05-01" for r in results)

    def test_no_as_of_returns_all_ticker_records(self, memory):
        dates = {r.date for r in memory.search_by_ticker("600519", top_k=10)}
        assert dates == {"2025-05-01", "2026-08-01"}


class _FakeChromaCollection:
    """故意**忽略** ``where`` 的假集合，用来验证兜底过滤有效。"""

    def __init__(self, rows):
        self.rows = rows
        self.queries: list[dict] = []

    def count(self):
        return len(self.rows)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {
            "documents": [[r["content"] for r in self.rows]],
            "metadatas": [[{k: v for k, v in r.items() if k != "content"} for r in self.rows]],
            "distances": [[0.1] * len(self.rows)],
        }


class TestChromaBackendGating:
    """chroma 后端：既能下发 where，也能在后端忽略 where 时兜底。"""

    @pytest.fixture
    def chroma_memory(self):
        mem = MarketMemory(backend="tfidf", persist_dir=None)
        mem._backend = "chroma"
        mem._chroma_collection = _FakeChromaCollection(
            [
                {
                    "ticker": "600519",
                    "date": "2025-05-01",
                    "chunk_index": 0,
                    "rating": "增持",
                    "keywords": "白酒",
                    "content": "去年的分析",
                },
                {
                    "ticker": "600519",
                    "date": "2026-08-01",
                    "chunk_index": 0,
                    "rating": "买入",
                    "keywords": "白酒",
                    "content": "未来的分析",
                },
            ]
        )
        return mem

    def test_where_clause_is_pushed_down(self, chroma_memory):
        chroma_memory.search(_QUERY, top_k=5, as_of="2025-06-01")
        assert chroma_memory._chroma_collection.queries[0]["where"] == {"date": {"$lte": "2025-06-01"}}

    def test_no_where_clause_without_as_of(self, chroma_memory):
        chroma_memory.search(_QUERY, top_k=5)
        assert "where" not in chroma_memory._chroma_collection.queries[0]

    def test_post_filter_saves_us_when_backend_ignores_where(self, chroma_memory):
        """假集合无视 where 返回了全部两条 —— 兜底必须把未来那条拦掉。"""
        results = chroma_memory.search(_QUERY, top_k=5, as_of="2025-06-01")
        assert [r.date for r in results] == ["2025-05-01"]

    def test_records_are_parsed_from_metadata(self, chroma_memory):
        results = chroma_memory.search(_QUERY, top_k=5, as_of="2025-06-01")
        assert results[0].ticker == "600519"
        assert results[0].rating == "增持"
        assert results[0].keywords == ["白酒"]
