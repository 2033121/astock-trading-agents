"""外部校准接入（issue #1 试点支撑）测试。

覆盖三条硬约束：
1. 题域边界声明必须随结果一起出现；
2. 无凭据时全链路优雅跳过、绝不抛异常，且凭据只从环境变量读取；
3. 外部结算台账与内部交易记忆物理隔离。
"""

import json
from pathlib import Path

import pytest

from astock_trader.external_calibration import (
    ASSET_DOMAIN_BOUNDARY,
    ENV_AGENT_ID,
    SOURCE_TAG,
    ArenaSettlement,
    CalibrationBucketRow,
    ExternalCalibrationLedger,
    HeadlineArenaClient,
    LocalStance,
    build_buckets,
    reconcile,
    render_markdown,
)
from astock_trader.external_calibration.ledger import RECORD_SETTLEMENT, RECORD_STANCE

# ────────────────────────────────────────────────────────────────
#  测试替身
# ────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class _FakeSession:
    """记录调用并按序返回预设响应。"""

    def __init__(self, responses=None, exception=None):
        self.calls = []
        self._responses = list(responses or [])
        self._exception = exception

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self._exception is not None:
            raise self._exception
        if self._responses:
            return self._responses.pop(0)
        return _FakeResponse(200, {})


def _prediction(**overrides):
    """一条平台预测历史条目（对齐 PredictionHistoryItem）。"""
    item = {
        "prediction_id": "p1",
        "challenge_id": "c1",
        "asset": "GC",
        "question": "Will gold close higher?",
        "direction": "bullish",
        "confidence": 0.7,
        "is_correct": True,
        "score": 0.5,
        "result": "bullish",
        "created_at": "2026-09-01T00:00:00Z",
    }
    item.update(overrides)
    return item


@pytest.fixture
def ledger(tmp_path) -> ExternalCalibrationLedger:
    return ExternalCalibrationLedger(project_dir=str(tmp_path))


# ────────────────────────────────────────────────────────────────
#  schema
# ────────────────────────────────────────────────────────────────


class TestSchema:
    def test_from_api_item_maps_platform_fields(self):
        s = ArenaSettlement.from_api_item(_prediction())
        assert s.prediction_id == "p1"
        assert s.challenge_id == "c1"
        assert s.asset == "GC"
        assert s.direction == "bullish"
        assert s.confidence == pytest.approx(0.7)
        assert s.result == "bullish"
        assert s.is_correct is True
        assert s.ingested_at, "入库时间应自动补全"

    def test_every_settlement_is_source_tagged(self):
        assert ArenaSettlement.from_api_item(_prediction()).source == SOURCE_TAG

    def test_unresolved_settlement_has_no_verdict(self):
        s = ArenaSettlement.from_api_item(_prediction(result=None, is_correct=None))
        assert s.is_resolved is False
        assert s.is_hit is None

    def test_hit_falls_back_to_direction_comparison(self):
        """平台未给 is_correct 时，用冻结的 result 机械比对方向。"""
        s = ArenaSettlement.from_api_item(_prediction(is_correct=None, result="bearish"))
        assert s.is_hit is False

    def test_api_item_with_missing_fields_does_not_raise(self):
        s = ArenaSettlement.from_api_item({})
        assert s.prediction_id == ""
        assert s.confidence == pytest.approx(0.0)

    def test_local_stance_roundtrip_ignores_unknown_keys(self):
        stance = LocalStance(challenge_id="c1", direction="bullish", confidence=0.6)
        restored = LocalStance.from_dict({**stance.to_dict(), "record_type": RECORD_STANCE, "junk": 1})
        assert restored.challenge_id == "c1"
        assert restored.source == SOURCE_TAG

    def test_bucket_gap_sign_convention(self):
        overconfident = CalibrationBucketRow(bucket="90-100", n=10, avg_confidence=0.95, hit_rate=0.6)
        underconfident = CalibrationBucketRow(bucket="50-60", n=10, avg_confidence=0.55, hit_rate=0.8)
        assert overconfident.gap < 0  # 负值 = 过度自信
        assert underconfident.gap > 0  # 正值 = 偏保守

    def test_domain_boundary_states_it_is_not_a_verdict(self):
        assert "不能" in ASSET_DOMAIN_BOUNDARY
        assert "通用反作弊参照" in ASSET_DOMAIN_BOUNDARY


# ────────────────────────────────────────────────────────────────
#  arena client — 无凭据优雅跳过
# ────────────────────────────────────────────────────────────────


class TestClientGracefulSkip:
    def test_unconfigured_client_reports_not_configured(self):
        client = HeadlineArenaClient(env={})
        assert client.is_configured is False
        assert client.has_credentials is False

    def test_unconfigured_reads_return_none_without_network(self):
        session = _FakeSession()
        client = HeadlineArenaClient(env={}, session=session)
        assert client.fetch_predictions() is None
        assert client.fetch_calibration() is None
        assert client.fetch_scorecard() is None
        assert session.calls == [], "未配置时不应发起任何请求"

    def test_unconfigured_iteration_yields_nothing(self):
        client = HeadlineArenaClient(env={}, session=_FakeSession())
        assert list(client.iter_predictions()) == []

    def test_agent_id_alone_is_enough_for_public_reads(self):
        """公开端点不需要 client_secret，只有 agent_id 也应可用。"""
        client = HeadlineArenaClient(env={ENV_AGENT_ID: "agent-1"})
        assert client.is_configured is True
        assert client.has_credentials is False

    def test_access_token_none_without_credentials(self):
        assert HeadlineArenaClient(env={ENV_AGENT_ID: "agent-1"}).access_token() is None


# ────────────────────────────────────────────────────────────────
#  arena client — 请求行为与失败降级
# ────────────────────────────────────────────────────────────────


class TestClientRequests:
    def _client(self, session, **kwargs):
        return HeadlineArenaClient(agent_id="agent-1", session=session, **kwargs)

    def test_fetch_predictions_hits_documented_endpoint(self):
        session = _FakeSession([_FakeResponse(200, {"items": [_prediction()], "total": 1})])
        items = self._client(session).fetch_predictions()["items"]
        call = session.calls[0]
        assert call["method"] == "GET"
        assert call["url"].endswith("/eval/agents/agent-1/predictions")
        assert call["params"]["limit"] == 100
        assert len(items) == 1

    def test_since_is_forwarded_for_incremental_sync(self):
        session = _FakeSession([_FakeResponse(200, {"items": []})])
        self._client(session).fetch_predictions(since="2026-09-01T00:00:00Z")
        assert session.calls[0]["params"]["since"] == "2026-09-01T00:00:00Z"

    def test_limit_is_clamped_to_platform_maximum(self):
        session = _FakeSession([_FakeResponse(200, {"items": []})])
        self._client(session).fetch_predictions(limit=9999)
        assert session.calls[0]["params"]["limit"] == 100

    def test_iter_predictions_paginates_and_stops(self):
        page1 = [_prediction(prediction_id=f"p{i}") for i in range(100)]
        page2 = [_prediction(prediction_id=f"q{i}") for i in range(50)]
        session = _FakeSession(
            [
                _FakeResponse(200, {"items": page1, "total": 150}),
                _FakeResponse(200, {"items": page2, "total": 150}),
            ]
        )
        collected = list(self._client(session).iter_predictions())
        assert len(collected) == 150
        assert len(session.calls) == 2
        assert session.calls[1]["params"]["offset"] == 100

    def test_iter_predictions_stops_on_short_page(self):
        session = _FakeSession([_FakeResponse(200, {"items": [_prediction()], "total": 1})])
        assert len(list(self._client(session).iter_predictions())) == 1
        assert len(session.calls) == 1

    def test_iter_predictions_survives_failing_second_page(self):
        session = _FakeSession([_FakeResponse(200, {"items": [_prediction()], "total": 999})])
        session._responses.append(_FakeResponse(500, {}))
        collected = list(self._client(session).iter_predictions(page_size=1))
        assert len(collected) == 1, "首页数据应保留，失败页安静终止"

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
    def test_http_errors_degrade_to_none(self, status):
        session = _FakeSession([_FakeResponse(status, {})])
        assert self._client(session).fetch_calibration() is None

    def test_network_exception_degrades_to_none(self):
        session = _FakeSession(exception=ConnectionError("boom"))
        assert self._client(session).fetch_predictions() is None

    def test_non_json_body_degrades_to_none(self):
        session = _FakeSession([_FakeResponse(200, bad_json=True)])
        assert self._client(session).fetch_scorecard() is None

    def test_unexpected_payload_shape_degrades_to_none(self):
        session = _FakeSession([_FakeResponse(200, ["not", "a", "dict"])])
        assert self._client(session).fetch_calibration() is None

    def test_calibration_and_scorecard_endpoints(self):
        session = _FakeSession([_FakeResponse(200, {"total": 3, "buckets": []}), _FakeResponse(200, {"rank": 1})])
        client = self._client(session)
        assert client.fetch_calibration()["total"] == 3
        assert client.fetch_scorecard()["rank"] == 1
        assert session.calls[0]["url"].endswith("/eval/agents/agent-1/calibration")
        assert session.calls[1]["url"].endswith("/eval/agents/agent-1/scorecard")

    def test_requests_always_carry_user_agent(self):
        """平台前置网关对缺少 UA 的请求直接 403（2026-09 实机验证）。"""
        session = _FakeSession([_FakeResponse(200, {"items": []})])
        self._client(session).fetch_predictions()
        assert session.calls[0]["headers"]["User-Agent"]
        assert session.calls[0]["headers"]["Accept"] == "application/json"


class TestClientCredentials:
    def test_token_is_fetched_with_client_credentials_and_cached(self):
        session = _FakeSession([_FakeResponse(200, {"access_token": "tok-1", "expires_in": 3600})])
        client = HeadlineArenaClient(agent_id="agent-1", client_secret="sec", session=session)
        assert client.access_token() == "tok-1"
        assert client.access_token() == "tok-1"
        assert len(session.calls) == 1, "第二次调用应命中内存缓存"
        body = session.calls[0]["json"]
        assert body["grant_type"] == "client_credentials"
        assert body["agent_id"] == "agent-1"

    def test_token_failure_returns_none(self):
        session = _FakeSession([_FakeResponse(401, {})])
        client = HeadlineArenaClient(agent_id="agent-1", client_secret="bad", session=session)
        assert client.access_token() is None

    def test_response_without_access_token_returns_none(self):
        session = _FakeSession([_FakeResponse(200, {"detail": "nope"})])
        client = HeadlineArenaClient(agent_id="agent-1", client_secret="sec", session=session)
        assert client.access_token() is None

    def test_preset_token_takes_precedence_and_skips_network(self):
        session = _FakeSession()
        client = HeadlineArenaClient(agent_id="agent-1", client_secret="sec", token="preset", session=session)
        assert client.access_token() == "preset"
        assert session.calls == []

    def test_credentials_are_read_from_environment(self):
        env = {
            ENV_AGENT_ID: "agent-9",
            "HEADLINE_ARENA_CLIENT_SECRET": "sec",
            "HEADLINE_ARENA_BASE_URL": "https://example.test/api/v1/",
        }
        client = HeadlineArenaClient(env=env)
        assert client.agent_id == "agent-9"
        assert client.has_credentials is True
        assert client.base_url == "https://example.test/api/v1", "尾部斜杠应被规整"

    def test_client_never_exposes_secret(self):
        client = HeadlineArenaClient(agent_id="a", client_secret="super-secret", env={})
        assert "super-secret" not in repr(client), "默认 repr 不应泄漏凭据"

    def test_secret_never_lands_in_ledger_or_report(self, tmp_path):
        """凭据纪律：secret 只用于换 token，绝不写入台账或比对报告。"""
        secret = "super-secret-value"
        session = _FakeSession([_FakeResponse(200, {"items": [_prediction()]})])
        client = HeadlineArenaClient(agent_id="agent-1", client_secret=secret, session=session)
        ledger = ExternalCalibrationLedger(project_dir=str(tmp_path))
        ledger.sync(client)
        report = render_markdown(reconcile(ledger, agent_id=client.agent_id))
        assert secret not in ledger.path.read_text(encoding="utf-8")
        assert secret not in report


# ────────────────────────────────────────────────────────────────
#  ledger — 来源隔离
# ────────────────────────────────────────────────────────────────


class TestLedgerIsolation:
    def test_default_path_is_not_internal_memory(self, tmp_path):
        path = ExternalCalibrationLedger(project_dir=str(tmp_path)).path
        assert path.parent.name == "external_calibration"
        assert path.name == "headline_arena_ledger.jsonl"
        assert path.name not in {"trading_memory.log", "trading_memory.md"}

    @pytest.mark.parametrize("forbidden", ["trading_memory.log", "trading_memory.md"])
    def test_refuses_internal_memory_filenames(self, tmp_path, forbidden):
        with pytest.raises(ValueError, match="内部交易记忆"):
            ExternalCalibrationLedger(ledger_dir=str(tmp_path), ledger_file=forbidden)

    def test_refuses_default_internal_memory_path(self):
        home = Path.home() / ".astock_trader"
        with pytest.raises(ValueError, match="内部交易记忆"):
            ExternalCalibrationLedger(ledger_dir=str(home), ledger_file="trading_memory.log")

    def test_every_persisted_record_carries_source_tag(self, ledger):
        ledger.record_settlement(ArenaSettlement.from_api_item(_prediction()))
        ledger.record_stance(LocalStance(challenge_id="c1", direction="bullish", confidence=0.5))
        records = [json.loads(line) for line in ledger.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert records, "台账应有内容"
        assert all(r["source"] == SOURCE_TAG for r in records)
        assert {r["record_type"] for r in records} == {RECORD_SETTLEMENT, RECORD_STANCE}

    def test_ledger_does_not_touch_trading_memory(self, ledger, tmp_path):
        ledger.record_settlement(ArenaSettlement.from_api_item(_prediction()))
        assert not list(tmp_path.glob("**/trading_memory.*"))


# ────────────────────────────────────────────────────────────────
#  ledger — 写入语义
# ────────────────────────────────────────────────────────────────


class TestLedgerWrites:
    def test_first_settlement_is_new_second_is_update(self, ledger):
        first = ledger.record_settlement(ArenaSettlement.from_api_item(_prediction()))
        second = ledger.record_settlement(ArenaSettlement.from_api_item(_prediction()))
        assert first is True
        assert second is False
        assert len(ledger.load_settlements()) == 1, "重复结算应幂等"

    def test_settlement_update_wins_last(self, ledger):
        ledger.record_settlement(ArenaSettlement.from_api_item(_prediction(result=None, is_correct=None)))
        ledger.record_settlement(ArenaSettlement.from_api_item(_prediction(result="bearish", is_correct=False)))
        loaded = ledger.load_settlements()[0]
        assert loaded.is_resolved is True
        assert loaded.is_hit is False

    def test_settlement_without_prediction_id_is_dropped(self, ledger):
        dropped = ArenaSettlement.from_api_item(_prediction(prediction_id=""))
        assert ledger.record_settlement(dropped) is False
        assert ledger.load_settlements() == []

    def test_stance_is_frozen_write_once(self, ledger):
        original = LocalStance(challenge_id="c1", direction="bullish", confidence=0.7)
        revised = LocalStance(challenge_id="c1", direction="bearish", confidence=0.2)
        assert ledger.record_stance(original) is True
        assert ledger.record_stance(revised) is False, "默认拒绝覆盖，防止事后回填"
        assert ledger.load_stances()["c1"].direction == "bullish"

    def test_stance_can_be_overwritten_explicitly(self, ledger):
        ledger.record_stance(LocalStance(challenge_id="c1", direction="bullish", confidence=0.7))
        assert ledger.record_stance(LocalStance(challenge_id="c1", direction="bearish", confidence=0.2), overwrite=True)
        assert ledger.load_stances()["c1"].direction == "bearish"

    def test_stance_without_challenge_id_is_dropped(self, ledger):
        assert ledger.record_stance(LocalStance(challenge_id="", direction="bullish", confidence=0.5)) is False
        assert ledger.load_stances() == {}

    def test_recorded_at_is_auto_filled(self, ledger):
        ledger.record_stance(LocalStance(challenge_id="c1", direction="bullish", confidence=0.5))
        assert ledger.load_stances()["c1"].recorded_at

    def test_corrupt_line_is_skipped(self, ledger):
        ledger.record_settlement(ArenaSettlement.from_api_item(_prediction()))
        with open(ledger.path, "a", encoding="utf-8") as f:
            f.write("{not json at all\n")
        ledger.record_stance(LocalStance(challenge_id="c1", direction="bullish", confidence=0.5))
        assert len(ledger.load_settlements()) == 1
        assert len(ledger.load_stances()) == 1

    def test_empty_ledger_loads_empty(self, ledger):
        assert ledger.load_settlements() == []
        assert ledger.load_stances() == {}
        assert ledger.stats()["settlements"] == 0

    def test_stats_counts_resolved_and_pending(self, ledger):
        ledger.record_settlement(ArenaSettlement.from_api_item(_prediction(prediction_id="p1")))
        ledger.record_settlement(
            ArenaSettlement.from_api_item(_prediction(prediction_id="p2", result=None, is_correct=None))
        )
        stats = ledger.stats()
        assert stats["settlements"] == 2
        assert stats["resolved"] == 1
        assert stats["pending"] == 1
        assert stats["source"] == SOURCE_TAG


# ────────────────────────────────────────────────────────────────
#  ledger — 同步
# ────────────────────────────────────────────────────────────────


class TestLedgerSync:
    def test_sync_ingests_predictions(self, ledger):
        session = _FakeSession([_FakeResponse(200, {"items": [_prediction(), _prediction(prediction_id="p2")]})])
        client = HeadlineArenaClient(agent_id="agent-1", session=session)
        assert ledger.sync(client) == 2
        assert len(ledger.load_settlements()) == 2

    def test_sync_is_idempotent(self, ledger):
        payload = {"items": [_prediction()]}
        session = _FakeSession([_FakeResponse(200, payload), _FakeResponse(200, payload)])
        client = HeadlineArenaClient(agent_id="agent-1", session=session)
        assert ledger.sync(client) == 1
        assert ledger.sync(client) == 0

    def test_sync_with_unconfigured_client_is_a_noop(self, ledger):
        client = HeadlineArenaClient(env={}, session=_FakeSession())
        assert ledger.sync(client) == 0
        assert ledger.load_settlements() == []

    def test_sync_skips_items_without_primary_keys(self, ledger):
        session = _FakeSession([_FakeResponse(200, {"items": [{"asset": "GC"}, _prediction()]})])
        client = HeadlineArenaClient(agent_id="agent-1", session=session)
        assert ledger.sync(client) == 1


# ────────────────────────────────────────────────────────────────
#  reconciliation
# ────────────────────────────────────────────────────────────────


def _seed_two_lines(ledger):
    """arena 一胜一负；本地镜像两胜；方向一致率 50%。"""
    ledger.record_settlement(
        ArenaSettlement.from_api_item(
            _prediction(prediction_id="p1", challenge_id="c1", direction="bullish", confidence=0.7, result="bullish")
        )
    )
    ledger.record_settlement(
        ArenaSettlement.from_api_item(
            _prediction(
                prediction_id="p2",
                challenge_id="c2",
                direction="bullish",
                confidence=0.6,
                result="bearish",
                is_correct=False,
            )
        )
    )
    ledger.record_settlement(
        ArenaSettlement.from_api_item(_prediction(prediction_id="p3", challenge_id="c3", result=None, is_correct=None))
    )
    ledger.record_stance(LocalStance(challenge_id="c1", direction="bullish", confidence=0.8))
    ledger.record_stance(LocalStance(challenge_id="c2", direction="bearish", confidence=0.5))


class TestReconciliation:
    def test_arena_line_stats(self, ledger):
        _seed_two_lines(ledger)
        report = reconcile(ledger)
        assert report.arena.n == 2
        assert report.arena.hits == 1
        assert report.arena.hit_rate == pytest.approx(0.5)
        assert report.arena.avg_confidence == pytest.approx(0.65)
        assert report.arena.brier == pytest.approx(0.225)  # ((0.7-1)² + (0.6-0)²) / 2

    def test_mirror_line_scored_against_frozen_result(self, ledger):
        _seed_two_lines(ledger)
        report = reconcile(ledger)
        assert report.mirror is not None
        assert report.mirror.n == 2
        assert report.mirror.hits == 2
        assert report.mirror.hit_rate == pytest.approx(1.0)
        assert report.mirror.brier == pytest.approx(0.145)  # ((0.8-1)² + (0.5-1)²) / 2

    def test_agreement_rate_between_the_two_lines(self, ledger):
        _seed_two_lines(ledger)
        assert reconcile(ledger).agreement_rate == pytest.approx(0.5)

    def test_pending_counted_separately(self, ledger):
        _seed_two_lines(ledger)
        report = reconcile(ledger)
        assert report.pending == 1
        assert report.matched_pairs == 2

    def test_unmatched_settlements_leave_mirror_empty(self, ledger):
        ledger.record_settlement(ArenaSettlement.from_api_item(_prediction()))
        report = reconcile(ledger)
        assert report.mirror is None
        assert report.agreement_rate is None
        assert any("本地镜像判断" in n for n in report.notes)

    def test_empty_ledger_is_not_an_error(self, ledger):
        report = reconcile(ledger)
        assert report.arena.n == 0
        assert report.arena.hit_rate is None
        assert report.mirror is None
        assert any("sync" in n for n in report.notes)

    def test_small_sample_is_flagged(self, ledger):
        _seed_two_lines(ledger)
        assert any("结论仅供方向性参考" in n for n in reconcile(ledger).notes)

    def test_tiny_mirror_sample_is_flagged(self, ledger):
        """镜像线样本极少时不能让人把 100% 当成校准良好。"""
        _seed_two_lines(ledger)
        assert any("本地镜像线仅 2 条" in n for n in reconcile(ledger).notes)

    def test_partial_pairing_coverage_is_flagged(self, ledger):
        _seed_two_lines(ledger)
        ledger.record_settlement(ArenaSettlement.from_api_item(_prediction(prediction_id="p9", challenge_id="c9")))
        report = reconcile(ledger)
        assert any("配对覆盖率 2/3" in n for n in report.notes)

    def test_full_coverage_produces_no_coverage_note(self, ledger):
        _seed_two_lines(ledger)
        assert not any("配对覆盖率" in n for n in reconcile(ledger).notes)

    def test_boundary_is_always_attached(self, ledger):
        _seed_two_lines(ledger)
        report = reconcile(ledger)
        assert report.boundary == ASSET_DOMAIN_BOUNDARY
        assert report.to_dict()["boundary"] == ASSET_DOMAIN_BOUNDARY

    def test_scorecard_and_agent_id_are_carried_through(self, ledger):
        report = reconcile(ledger, scorecard={"overall_score": 1.5, "rank": 7}, agent_id="agent-1")
        assert report.agent_id == "agent-1"
        assert report.scorecard["rank"] == 7
        assert report.to_dict()["scorecard"]["overall_score"] == 1.5

    def test_generated_at_is_set(self, ledger):
        assert reconcile(ledger, generated_at="2026-09-19T00:00:00+00:00").generated_at == "2026-09-19T00:00:00+00:00"


class TestBuckets:
    def test_build_buckets_from_platform_payload(self):
        rows = build_buckets(
            {
                "total": 2,
                "buckets": [
                    {"bucket": "50-60", "n": 12, "avg_confidence": 0.55, "hit_rate": 0.58, "low_sample": False},
                    {"bucket": "90-100", "n": 2, "avg_confidence": 0.93, "hit_rate": 0.5, "low_sample": True},
                ],
            }
        )
        assert len(rows) == 2
        assert rows[1].low_sample is True
        assert rows[1].gap == pytest.approx(-0.43)

    @pytest.mark.parametrize("payload", [None, {}, {"buckets": None}, {"buckets": "nope"}])
    def test_build_buckets_tolerates_missing_or_bad_payload(self, payload):
        assert build_buckets(payload) == []

    def test_build_buckets_skips_unparsable_rows(self):
        rows = build_buckets({"buckets": [{"bucket": "x", "n": "abc"}, {"bucket": "y", "n": 3}]})
        assert len(rows) == 1
        assert rows[0].bucket == "y"


class TestMarkdownReport:
    def test_report_states_the_domain_boundary(self, ledger):
        _seed_two_lines(ledger)
        text = render_markdown(reconcile(ledger))
        assert ASSET_DOMAIN_BOUNDARY in text
        assert "不能" in text

    def test_report_contains_both_lines_and_metrics(self, ledger):
        _seed_two_lines(ledger)
        text = render_markdown(
            reconcile(
                ledger,
                calibration={
                    "buckets": [
                        {"bucket": "60-70", "n": 20, "avg_confidence": 0.65, "hit_rate": 0.6, "low_sample": False}
                    ]
                },
            )
        )
        assert "arena（第三方机械结算）" in text
        assert "本地镜像（内部宏观判断）" in text
        assert "50.0%" in text
        assert "60-70" in text

    def test_report_handles_empty_ledger(self, ledger):
        text = render_markdown(reconcile(ledger))
        assert "外部校准比对报告" in text
        assert ASSET_DOMAIN_BOUNDARY in text

    def test_report_renders_scorecard_when_present(self, ledger):
        text = render_markdown(reconcile(ledger, scorecard={"overall_score": 2.0, "rank": 3, "trend": "up"}))
        assert "平台记分卡" in text
        assert "up" in text
