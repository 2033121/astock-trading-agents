"""新闻流不得把未来稿件塞进历史窗口。

两个真实缺陷：

1. ``get_news`` 在日期解析失败时 ``pass``，直接返回**全部**新闻 —— 回测于是读到
   了最新（未来）的稿件；
2. ``get_global_news`` 只在筛选结果**非空**时才采用过滤后的数据，窗口内一旦没有
   稿件就退回未过滤的全量数据，后果同样是历史窗口拿到未来新闻。

判据统一为 :func:`astock_trader.point_in_time.in_window`：按北京时间的日历天比较，
无发布时间的条目只在实时窗口（窗口抵达当下）才保留。
"""

from datetime import date, datetime

import pandas as pd
import pytest

from astock_trader.dataflows import eastmoney_news

_FAR_FUTURE = "2030-12-31"
_FAR_PAST = "2020-01-01"


class _FakeAk:
    """伪造 akshare 模块（测试环境里 akshare 通常没装，``ak`` 是 ``None``）。"""

    def __init__(self, stock_news=None, global_news=None, cls_news=None):
        self._stock_news = stock_news
        self._global_news = global_news
        self._cls_news = cls_news

    def stock_news_em(self, symbol):
        return self._stock_news

    def stock_info_global_em(self):
        return self._global_news

    def stock_info_global_cls(self):
        return self._cls_news


@pytest.fixture
def news_frame(monkeypatch):
    """把 ``ak.stock_news_em`` 换成可控的 DataFrame（全局新闻接口给空表）。"""

    def _install(rows):
        df = pd.DataFrame(rows)
        monkeypatch.setattr(
            eastmoney_news, "ak", _FakeAk(stock_news=df, global_news=pd.DataFrame(), cls_news=pd.DataFrame())
        )
        return df

    return _install


def _row(title: str, published) -> dict:
    """个股新闻的原始行（akshare ``stock_news_em`` 的中文列名）。"""
    return {
        "新闻标题": title,
        "新闻内容": f"{title} 的正文",
        "发布时间": published,
        "文章来源": "测试来源",
        "新闻链接": "https://example.invalid/x",
    }


def _global_row(title: str, published) -> dict:
    """全球新闻的原始行（akshare ``stock_info_global_em`` 的列名不同）。"""
    return {
        "标题": title,
        "内容": f"{title} 的正文",
        "发布时间": published,
        "来源": "测试来源",
    }


class TestGetNewsWindow:
    """个股新闻的窗口过滤。"""

    def test_future_article_is_dropped(self, news_frame):
        news_frame(
            [
                _row("历史稿件", "2025-05-03 10:00:00"),
                _row("次日稿件", "2025-05-08 09:00:00"),
            ]
        )
        out = eastmoney_news.get_news("600519", "2025-05-01", "2025-05-07")
        assert "历史稿件" in out
        assert "次日稿件" not in out

    def test_next_day_early_morning_is_dropped(self, news_frame):
        """次日凌晨（北京时间）按 UTC 解释会被误判为落在窗口内。"""
        news_frame([_row("凌晨稿件", "2025-05-08 00:30:00")])
        out = eastmoney_news.get_news("600519", "2025-05-01", "2025-05-07")
        assert "凌晨稿件" not in out
        assert "No news in range" in out

    def test_undated_article_dropped_in_historical_window(self, news_frame):
        """解析不出发布时间：回测里无法证明它不是未来，丢弃。"""
        news_frame([_row("无日期稿件", "不是时间"), _row("正常稿件", "2025-05-03 10:00:00")])
        out = eastmoney_news.get_news("600519", "2025-05-01", "2025-05-07")
        assert "无日期稿件" not in out
        assert "正常稿件" in out

    def test_unparseable_dates_do_not_leak_everything(self, news_frame):
        """核心回归：整列都解析不出来时，历史上是「返回全部」。"""
        news_frame([_row("稿件甲", "昨天"), _row("稿件乙", "上周")])
        out = eastmoney_news.get_news("600519", "2025-05-01", "2025-05-07")
        assert "稿件甲" not in out
        assert "稿件乙" not in out
        assert "No news in range" in out

    def test_undated_article_kept_in_live_window(self, news_frame):
        """实时窗口（end = 今天）保留无日期稿件 —— 与改动前行为一致。"""
        today = date.today().isoformat()
        news_frame([_row("无日期稿件", "不是时间")])
        out = eastmoney_news.get_news("600519", today, today)
        assert "无日期稿件" in out

    def test_missing_datetime_column_is_conservative(self, news_frame):
        """整列缺失等于「全部无发布时间」：历史窗口下不返回任何条目。"""
        news_frame([{"新闻标题": "甲", "新闻内容": "x", "文章来源": "s", "新闻链接": "u"}])
        out = eastmoney_news.get_news("600519", "2025-05-01", "2025-05-07")
        assert "甲" not in out


@pytest.fixture
def global_frame(monkeypatch):
    """把 ``ak.stock_info_global_em`` 换成可控的 DataFrame。"""

    def _install(rows):
        df = pd.DataFrame(rows)
        monkeypatch.setattr(eastmoney_news, "ak", _FakeAk(global_news=df))
        return df

    return _install


class TestGetGlobalNewsWindow:
    """全球新闻的窗口过滤。"""

    def test_window_applied_unconditionally(self, global_frame):
        """核心回归：窗口内筛不出稿件时也要保持过滤，而不是退回全量。"""
        global_frame([_global_row("未来稿件", "2025-06-20 10:00:00")])
        out = eastmoney_news.get_global_news("2025-05-07", look_back_days=7)
        assert "未来稿件" not in out
        assert "No news in window" in out

    def test_only_articles_inside_window_are_kept(self, global_frame):
        global_frame(
            [
                _global_row("窗口内", "2025-05-05 10:00:00"),
                _global_row("窗口前", "2025-04-20 10:00:00"),
                _global_row("窗口后", "2025-05-09 10:00:00"),
            ]
        )
        out = eastmoney_news.get_global_news("2025-05-07", look_back_days=7)
        assert "窗口内" in out
        assert "窗口前" not in out
        assert "窗口后" not in out

    def test_look_back_days_bounds_the_start(self, global_frame):
        """look_back_days=3 → 窗口是 [05-05, 05-07]。"""
        global_frame([_global_row("早于窗口", "2025-05-04 10:00:00"), _global_row("窗口内", "2025-05-05 10:00:00")])
        out = eastmoney_news.get_global_news("2025-05-07", look_back_days=3)
        assert "早于窗口" not in out
        assert "窗口内" in out

    def test_undated_dropped_in_historical_window(self, global_frame):
        global_frame([_global_row("无日期", ""), _global_row("有日期", "2025-05-06 10:00:00")])
        out = eastmoney_news.get_global_news("2025-05-07", look_back_days=7)
        assert "无日期" not in out
        assert "有日期" in out

    def test_live_window_keeps_undated(self, global_frame):
        today = date.today().isoformat()
        global_frame([_global_row("无日期", "")])
        out = eastmoney_news.get_global_news(today, look_back_days=7)
        assert "无日期" in out


class TestAsDatetimeHelper:
    """``_as_datetime`` 把 pandas 时间戳转成「可判定」或 ``None``。"""

    def test_nat_returns_none(self):
        assert eastmoney_news._as_datetime(pd.NaT) is None

    def test_none_returns_none(self):
        assert eastmoney_news._as_datetime(None) is None

    def test_timestamp_is_converted(self):
        value = eastmoney_news._as_datetime(pd.Timestamp("2025-05-03 10:00:00"))
        assert isinstance(value, datetime)
        assert value.hour == 10

    def test_datetime_passes_through(self):
        value = datetime(2025, 5, 3, 10, 0)
        assert eastmoney_news._as_datetime(value) is value


class TestInvalidReferenceDate:
    """参考日期本身非法时要给出明确提示，而不是抛异常或静默返回全量。"""

    def test_invalid_curr_date_reports_instead_of_raising(self, global_frame):
        global_frame([_global_row("某稿件", "2025-05-06 10:00:00")])
        out = eastmoney_news.get_global_news("不是日期", look_back_days=7)
        assert "Invalid curr_date" in out
        assert "某稿件" not in out
