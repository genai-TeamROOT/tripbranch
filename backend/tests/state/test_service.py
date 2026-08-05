"""계약 진입점 시나리오.

계약 문서: docs/package-b/agent-state-contract-v1.md (6절)

단위 테스트와 달리 여러 턴을 이어서 검증한다.
오늘 업무의 완료 기준 5개가 이 파일에서 확인된다.
"""

from datetime import timedelta

import pytest

from app.state import service as svc
from app.state.schema import now_kst
from app.state.store import InMemoryStateStore


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


def apply(store, **kwargs) -> svc.StateApplyResponse:
    """조건 적용 호출. 테스트 편의용 헬퍼."""
    kwargs.setdefault("intent", "RECOMMEND")
    kwargs.setdefault("confirmed", True)
    return svc.apply(svc.StateApplyRequest(**kwargs), store=store)


def record(store, session_id: str, run_id: str, places: list[tuple[str, int]]):
    return svc.record_recommendation(
        svc.RecordRecommendationRequest(
            session_id=session_id,
            run_id=run_id,
            recommended=[
                svc.RecommendedPlace(place_id=p, rank=r) for p, r in places
            ],
        ),
        store=store,
    )


# ================================================================ 완료 기준

class TestCompletionCriteria:
    """오늘 업무의 완료 기준 5개를 검증한다."""

    def test_기준1_조건_변경을_State에_적용한다(self, store):
        r = apply(
            store,
            session_id=None,
            operations=[
                {"op": "Update", "field": "search_center", "value": "경복궁"},
                {"op": "Update", "field": "place_types", "value": ["restaurant"]},
                {"op": "Add", "field": "place_tags", "value": ["카페"]},
            ],
        )

        assert r.user_conditions.search_center == "경복궁"
        assert r.user_conditions.place_types == ["restaurant"]
        assert r.user_conditions.place_tags == ["카페"]
        assert r.condition_changed is True
        assert r.condition_version == 1

    def test_기준2_변경_없는_재추천에서_조건이_유지된다(self, store):
        """MODIFY의 REJECT_ALL이 이 케이스에 해당한다."""
        first = apply(
            store,
            session_id=None,
            operations=[
                {"op": "Update", "field": "search_center", "value": "경복궁"},
                {"op": "Update", "field": "max_travel_time", "value": 15},
            ],
        )

        second = apply(
            store, session_id=first.session_id, intent="MODIFY", operations=[]
        )

        assert second.user_conditions.search_center == "경복궁"
        assert second.user_conditions.max_travel_time == 15
        assert second.condition_changed is False
        assert second.condition_version == first.condition_version

    def test_기준3_이력을_다음_요청에서_사용할_수_있다(self, store):
        first = apply(store, session_id=None, operations=[])
        sid = first.session_id

        record(store, sid, first.run_id, [("A", 1), ("B", 2), ("C", 3)])

        second = apply(store, session_id=sid, intent="MODIFY", operations=[])
        assert second.excluded_place_ids == ["A", "B", "C"]

        record(store, sid, second.run_id, [("D", 1), ("E", 2)])

        third = apply(store, session_id=sid, intent="MODIFY", operations=[])
        assert third.excluded_place_ids == ["A", "B", "C", "D", "E"]

    def test_기준4_초기화_후_이전_상태가_제거된다(self, store):
        first = apply(
            store,
            session_id=None,
            operations=[{"op": "Update", "field": "budget", "value": "free"}],
        )
        sid = first.session_id
        record(store, sid, first.run_id, [("A", 1), ("B", 2)])

        after = apply(
            store, session_id=sid, operations=[], reset_scope="full"
        )

        assert after.session_created is True
        assert after.session_id != sid
        assert after.user_conditions.budget is None
        assert after.excluded_place_ids == []

        # 이전 세션은 조회되지 않는다
        ctx = svc.get_session_context(sid, store=store)
        assert ctx.session_exists is False

    def test_기준5_A의_구조화_결과와_연결된다(self, store):
        """A 회신 형식(operations 배열)을 그대로 수신할 수 있어야 한다."""
        payload = {
            "session_id": None,
            "intent": "MODIFY",
            "confirmed": True,
            "reset_scope": None,
            "operations": [
                {
                    "op": "Update",
                    "field": "place_types",
                    "value": ["cultural_facility", "shopping"],
                },
                {"op": "Remove", "field": "place_tags", "value": ["카페"]},
            ],
            "rejected_places": [{"place_id": "126508", "reason_code": "too_far"}],
            "prompt_version": "intent_v1.2",
        }
        request = svc.StateApplyRequest(**payload)
        r = svc.apply(request, store=store)

        assert r.user_conditions.place_types == ["cultural_facility", "shopping"]
        assert "126508" in r.excluded_place_ids


# ================================================================ 6.1 / 6.2

class TestApply:
    def test_session_id가_없으면_신규_발급한다(self, store):
        r = apply(store, session_id=None, operations=[])

        assert r.session_created is True
        assert r.session_id.startswith("sess_")
        assert r.run_id.startswith("run_")

    def test_기존_세션은_재사용한다(self, store):
        first = apply(store, session_id=None, operations=[])
        second = apply(store, session_id=first.session_id, operations=[])

        assert second.session_created is False
        assert second.session_id == first.session_id

    def test_없는_세션은_오류가_아니라_신규_발급이다(self, store):
        """익명 세션에서 만료는 오류가 아니라 정상적인 생애주기다. (계약 5.2절)"""
        r = apply(store, session_id="sess_없음", operations=[])

        assert r.session_created is True
        assert r.session_id != "sess_없음"

    def test_매_요청마다_다른_run_id가_발급된다(self, store):
        first = apply(store, session_id=None, operations=[])
        second = apply(store, session_id=first.session_id, operations=[])

        assert first.run_id != second.run_id

    def test_무효한_연산은_ignored로_반환된다(self, store):
        r = apply(
            store,
            session_id=None,
            operations=[
                {"op": "Update", "field": "budget", "value": "free"},
                {"op": "Update", "field": "price", "value": 1000},
            ],
        )

        assert r.user_conditions.budget == "free"
        assert len(r.ignored_operations) == 1
        assert r.ignored_operations[0].reason == "unknown_field"

    def test_적용된_연산의_전후_값이_반환된다(self, store):
        """Package A가 사용자에게 변경 내용을 안내할 때 사용한다."""
        first = apply(
            store,
            session_id=None,
            operations=[{"op": "Update", "field": "max_travel_time", "value": 30}],
        )
        second = apply(
            store,
            session_id=first.session_id,
            operations=[{"op": "Update", "field": "max_travel_time", "value": 15}],
        )

        applied = second.applied_operations[0]
        assert applied.field == "max_travel_time"
        assert applied.before_value == 30
        assert applied.after_value == 15

    def test_intent가_저장된다(self, store):
        r = apply(store, session_id=None, intent="MODIFY", operations=[])
        ctx = svc.get_session_context(r.session_id, store=store)

        assert ctx.last_intent == "MODIFY"


class TestConfirmed:
    """확인 전 조건은 State에 반영하지 않는다. (계약 2.6절)"""

    def test_confirmed_False면_조건이_반영되지_않는다(self, store):
        first = apply(
            store,
            session_id=None,
            operations=[{"op": "Update", "field": "budget", "value": "free"}],
        )

        second = apply(
            store,
            session_id=first.session_id,
            confirmed=False,
            operations=[{"op": "Update", "field": "companion", "value": "parent"}],
        )

        assert second.user_conditions.companion is None
        assert second.user_conditions.budget == "free"
        assert second.condition_changed is False
        assert second.condition_version == first.condition_version

    def test_confirmed_False여도_run_id는_발급된다(self, store):
        r = apply(store, session_id=None, confirmed=False, operations=[])
        assert r.run_id.startswith("run_")

    def test_confirmed_False여도_세션은_생성된다(self, store):
        r = apply(store, session_id=None, confirmed=False, operations=[])
        assert r.session_created is True


class TestResetInApply:
    """계약 5.5절 초기화 범위."""

    def test_soft는_조건만_비우고_이력은_유지한다(self, store):
        first = apply(
            store,
            session_id=None,
            operations=[{"op": "Update", "field": "budget", "value": "free"}],
        )
        sid = first.session_id
        record(store, sid, first.run_id, [("A", 1)])

        after = apply(store, session_id=sid, operations=[], reset_scope="soft")

        assert after.user_conditions.budget is None
        assert after.excluded_place_ids == ["A"]
        assert after.session_id == sid

    def test_history는_조건을_유지하고_추천_이력만_비운다(self, store):
        first = apply(
            store,
            session_id=None,
            operations=[{"op": "Update", "field": "budget", "value": "free"}],
        )
        sid = first.session_id
        record(store, sid, first.run_id, [("A", 1), ("B", 2)])

        # B를 거절
        apply(
            store,
            session_id=sid,
            operations=[],
            rejected_places=[{"place_id": "B", "reason_code": "too_far"}],
        )

        after = apply(store, session_id=sid, operations=[], reset_scope="history")

        assert after.user_conditions.budget == "free"
        assert after.excluded_place_ids == ["B"]  # 거절만 남는다
        assert after.session_id == sid

    def test_reset이_operations보다_먼저_적용된다(self, store):
        """순서가 반대면 방금 적용한 조건이 지워진다. (계약 2.4절)"""
        first = apply(
            store,
            session_id=None,
            operations=[
                {"op": "Update", "field": "budget", "value": "free"},
                {"op": "Update", "field": "companion", "value": "parent"},
            ],
        )

        after = apply(
            store,
            session_id=first.session_id,
            operations=[{"op": "Update", "field": "environment", "value": "indoor"}],
            reset_scope="soft",
        )

        assert after.user_conditions.environment == "indoor"
        assert after.user_conditions.budget is None
        assert after.user_conditions.companion is None

    def test_reset_applied가_반환된다(self, store):
        r = apply(store, session_id=None, operations=[], reset_scope="soft")
        assert r.reset_applied == "soft"

    def test_reset이_없으면_None이다(self, store):
        r = apply(store, session_id=None, operations=[])
        assert r.reset_applied is None


# ================================================================ 6.3

class TestSessionContext:
    def test_없는_세션도_오류가_아니다(self, store):
        ctx = svc.get_session_context("sess_없음", store=store)

        assert ctx.session_exists is False
        assert ctx.has_recommendation is False
        assert ctx.recommended_count == 0

    def test_None을_전달해도_오류가_아니다(self, store):
        ctx = svc.get_session_context(None, store=store)
        assert ctx.session_exists is False

    def test_조회는_세션을_생성하지_않는다(self, store):
        """State를 변경하지 않는다. (계약 6.3절)"""
        svc.get_session_context("sess_없음", store=store)
        assert store.session_ids() == []

    def test_조회는_last_active_at을_갱신하지_않는다(self, store):
        r = apply(store, session_id=None, operations=[])
        before = store.get_state(r.session_id).last_active_at

        svc.get_session_context(r.session_id, store=store)

        assert store.get_state(r.session_id).last_active_at == before

    def test_추천_이력_존재_여부를_알려준다(self, store):
        """MODIFY / COMPARE 판정의 전제 조건이다."""
        r = apply(store, session_id=None, operations=[])
        sid = r.session_id

        assert svc.get_session_context(sid, store=store).has_recommendation is False

        record(store, sid, r.run_id, [("A", 1)])

        assert svc.get_session_context(sid, store=store).has_recommendation is True

    def test_shown은_마지막_실행_기준이다(self, store):
        """COMPARE의 "첫 번째"는 방금 본 추천을 가리킨다. (계약 3.4절)"""
        first = apply(store, session_id=None, operations=[])
        sid = first.session_id
        record(store, sid, first.run_id, [("A", 1), ("B", 2), ("C", 3)])

        second = apply(store, session_id=sid, operations=[])
        record(store, sid, second.run_id, [("D", 1), ("E", 2)])

        ctx = svc.get_session_context(sid, store=store)

        assert ctx.shown_place_ids == ["D", "E"]
        assert ctx.excluded_place_ids == ["A", "B", "C", "D", "E"]

    def test_현재_조건을_반환한다(self, store):
        """A가 "더 가까운 곳"의 절대값을 계산하려면 현재값이 필요하다."""
        r = apply(
            store,
            session_id=None,
            operations=[{"op": "Update", "field": "max_travel_time", "value": 30}],
        )

        ctx = svc.get_session_context(r.session_id, store=store)
        assert ctx.user_conditions.max_travel_time == 30

    def test_만료된_세션은_존재하지_않는_것으로_응답한다(self, store):
        r = apply(store, session_id=None, operations=[])

        state = store.get_state(r.session_id)
        state.last_active_at = now_kst() - timedelta(minutes=31)
        store.save_state(state)

        ctx = svc.get_session_context(r.session_id, store=store)
        assert ctx.session_exists is False


# ================================================================ 6.4

class TestRecordRecommendation:
    def test_기록_건수를_반환한다(self, store):
        r = apply(store, session_id=None, operations=[])
        res = record(store, r.session_id, r.run_id, [("A", 1), ("B", 2)])

        assert res.recorded == 2

    def test_기록한_장소가_제외_목록에_들어간다(self, store):
        first = apply(store, session_id=None, operations=[])
        record(store, first.session_id, first.run_id, [("A", 1)])

        second = apply(store, session_id=first.session_id, operations=[])
        assert "A" in second.excluded_place_ids

    def test_빈_목록도_오류가_아니다(self, store):
        r = apply(store, session_id=None, operations=[])
        res = record(store, r.session_id, r.run_id, [])
        assert res.recorded == 0


# ================================================================ 세션 삭제

class TestDeleteSession:
    def test_세션_상태와_이력을_삭제한다(self, store):
        first = apply(store, session_id=None, operations=[])
        sid = first.session_id
        record(store, sid, first.run_id, [("A", 1)])

        res = svc.delete_session(sid, store=store)

        assert res.session_id == sid
        assert res.deleted is True
        assert store.get_state(sid) is None
        assert store.get_history(sid) is None
        assert svc.get_session_context(sid, store=store).session_exists is False

    def test_없는_세션_삭제는_오류가_아니다(self, store):
        res = svc.delete_session("sess_없음", store=store)

        assert res.session_id == "sess_없음"
        assert res.deleted is False


# ================================================================ 6.5

class TestUpdateApiContext:
    def test_gps를_갱신한다(self, store):
        r = apply(store, session_id=None, operations=[])

        res = svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id=r.session_id, gps_location="37.5665,126.9780"
            ),
            store=store,
        )

        assert res is not None          # ← 추가
        assert res.api_context.gps_location == "37.5665,126.9780"
        assert res.api_context.gps_expired is False

    def test_condition_version을_증가시키지_않는다(self, store):
        """사용자가 조건을 바꾼 것이 아니기 때문이다. (계약 1.4절)"""
        r = apply(store, session_id=None, operations=[])
        before = store.get_state(r.session_id).condition_version

        svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id=r.session_id, gps_location="37.5,127.0"
            ),
            store=store,
        )

        assert store.get_state(r.session_id).condition_version == before

    def test_updated_at을_갱신하지_않는다(self, store):
        r = apply(store, session_id=None, operations=[])
        before = store.get_state(r.session_id).updated_at

        svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id=r.session_id, gps_location="37.5,127.0"
            ),
            store=store,
        )

        assert store.get_state(r.session_id).updated_at == before

    def test_전달된_필드만_갱신한다(self, store):
        """생략된 필드는 기존 값을 유지한다. (계약 6.5절)"""
        r = apply(store, session_id=None, operations=[])
        sid = r.session_id

        svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id=sid, gps_location="37.5,127.0", api_weather="rain"
            ),
            store=store,
        )
        # GPS만 갱신
        res = svc.update_api_context(
            svc.UpdateApiContextRequest(session_id=sid, gps_location="38.0,128.0"),
            store=store,
        )

        assert res is not None          # ← 추가

        
        assert res.api_context.gps_location == "38.0,128.0"
        assert res.api_context.api_weather == "rain"  # 유지된다

    def test_날씨_실패시_null_저장이_가능하다(self, store):
        """만료된 이전 값을 재사용하지 않는다. (계약 1.4절)"""
        r = apply(store, session_id=None, operations=[])
        sid = r.session_id

        svc.update_api_context(
            svc.UpdateApiContextRequest(session_id=sid, api_weather="rain"),
            store=store,
        )
        res = svc.update_api_context(
            svc.UpdateApiContextRequest(session_id=sid, api_weather=None),
            store=store,
        )

        assert res is not None          # ← 추가
        assert res.api_context.api_weather is None

    def test_없는_세션은_None을_반환하고_생성하지_않는다(self, store):
        res = svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id="sess_없음", gps_location="37.5,127.0"
            ),
            store=store,
        )

        assert res is None
        assert store.session_ids() == []

    def test_확보된_적_없으면_만료로_간주한다(self, store):
        r = apply(store, session_id=None, operations=[])

        assert r.api_context.gps_expired is True
        assert r.api_context.weather_expired is True


# ================================================================ 다중 턴

class TestMultiTurnScenario:
    def test_전체_대화_흐름(self, store):
        """1턴 추천 → 2턴 재추천 → 3턴 조건 변경 → 4턴 초기화."""
        # 1턴: 첫 추천
        t1 = apply(
            store,
            session_id=None,
            intent="RECOMMEND",
            operations=[
                {"op": "Update", "field": "search_center", "value": "경복궁"},
                {"op": "Update", "field": "place_types", "value": ["restaurant"]},
                {"op": "Add", "field": "place_tags", "value": ["카페"]},
            ],
        )
        sid = t1.session_id
        record(store, sid, t1.run_id, [("A", 1), ("B", 2), ("C", 3)])

        assert t1.condition_version == 1

        # 2턴: REJECT_ALL — 조건 유지, 이력 누적
        t2 = apply(store, session_id=sid, intent="MODIFY", operations=[])
        record(store, sid, t2.run_id, [("D", 1), ("E", 2)])

        assert t2.condition_changed is False
        assert t2.condition_version == 1
        assert t2.excluded_place_ids == ["A", "B", "C"]

        # 3턴: 조건 변경 + 거절
        t3 = apply(
            store,
            session_id=sid,
            intent="MODIFY",
            operations=[{"op": "Update", "field": "budget", "value": "free"}],
            rejected_places=[{"place_id": "D", "reason_code": "too_far"}],
        )

        assert t3.condition_version == 2
        assert t3.user_conditions.search_center == "경복궁"  # 이전 조건 유지
        assert t3.user_conditions.budget == "free"
        assert set(t3.excluded_place_ids) == {"A", "B", "C", "D", "E"}

        # 4턴: history reset — 조건 유지, 거절만 남음
        t4 = apply(
            store, session_id=sid, intent="RECOMMEND", operations=[], reset_scope="history"
        )

        assert t4.user_conditions.budget == "free"
        assert t4.excluded_place_ids == ["D"]
        assert t4.session_id == sid

    def test_변경_기록이_run_id로_묶인다(self, store):
        t1 = apply(
            store,
            session_id=None,
            operations=[{"op": "Update", "field": "budget", "value": "free"}],
        )
        t2 = apply(
            store,
            session_id=t1.session_id,
            operations=[{"op": "Update", "field": "companion", "value": "parent"}],
        )

        logs = store.get_change_logs(t1.session_id)
        run_ids = {log.run_id for log in logs}

        assert run_ids == {t1.run_id, t2.run_id}

# ---------------------------------------------------------------- 되묻기 플래그

def _session(store: InMemoryStateStore) -> str:
    """조건 적용으로 세션 하나를 만든다."""
    response = svc.apply(
        svc.StateApplyRequest(intent="RECOMMEND", confirmed=True),
        store=store,
    )
    return response.session_id


def test_set_pending_clarification_stores_and_exposes_code() -> None:
    store = InMemoryStateStore()
    session_id = _session(store)

    result = svc.set_pending_clarification(
        svc.SetPendingClarificationRequest(session_id=session_id, code="location_required"),
        store=store,
    )

    assert result is not None
    assert result.pending_clarification == "location_required"
    context = svc.get_session_context(session_id, store=store)
    assert context.pending_clarification == "location_required"


def test_set_pending_clarification_clears_with_none() -> None:
    store = InMemoryStateStore()
    session_id = _session(store)
    svc.set_pending_clarification(
        svc.SetPendingClarificationRequest(session_id=session_id, code="location_required"),
        store=store,
    )

    svc.set_pending_clarification(
        svc.SetPendingClarificationRequest(session_id=session_id, code=None), store=store
    )

    assert svc.get_session_context(session_id, store=store).pending_clarification is None


def test_set_pending_clarification_does_not_touch_conditions() -> None:
    """api_context 갱신과 같은 성격이라 조건 버전을 올리지 않는다."""
    store = InMemoryStateStore()
    session_id = _session(store)
    before = svc.get_session_context(session_id, store=store).condition_version

    svc.set_pending_clarification(
        svc.SetPendingClarificationRequest(session_id=session_id, code="location_required"),
        store=store,
    )

    after = svc.get_session_context(session_id, store=store)
    assert after.condition_version == before
    assert after.user_conditions == svc.get_session_context(session_id, store=store).user_conditions


def test_set_pending_clarification_returns_none_for_missing_session() -> None:
    store = InMemoryStateStore()

    result = svc.set_pending_clarification(
        svc.SetPendingClarificationRequest(session_id="sess_missing", code="x"), store=store
    )

    assert result is None
