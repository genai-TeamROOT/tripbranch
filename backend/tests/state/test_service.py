"""계약 진입점 시나리오.

계약 문서: docs/package-b/agent-state-contract-v1.md (6절)

단위 테스트와 달리 여러 턴을 이어서 검증한다.
오늘 업무의 완료 기준 5개가 이 파일에서 확인된다.
"""

from datetime import timedelta

import pytest

from app.auth.principal import Principal
from app.state import service as svc
from app.state.errors import SessionOwnershipError
from app.state.schema import PendingInfoContext, now_kst
from app.state.store import InMemoryStateStore


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


def apply(store, *, principal=None, **kwargs) -> svc.StateApplyResponse:
    """조건 적용 호출. 테스트 편의용 헬퍼."""
    kwargs.setdefault("intent", "RECOMMEND")
    kwargs.setdefault("confirmed", True)
    return svc.apply(svc.StateApplyRequest(**kwargs), store=store, principal=principal)


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


class TestApplyUserId:
    """TP-101 3단계, D-063 — apply()가 세션 확보 직후 신원을 연결한다.

    confirmed=False 조기 반환 경로와 본 경로 둘 다에서 저장되는지 확인한다
    (service.py의 "1-1) 신원 연결" 주석이 가리키는 두 저장 지점).
    """

    def test_principal이_없으면_user_id가_비어있다(self, store):
        r = apply(store, session_id=None, operations=[])
        assert store.get_state(r.session_id).user_id is None

    def test_빈_세션에_principal이_있으면_user_id가_채워진다(self, store):
        principal = Principal(user_id="user-1", is_anonymous=True)
        r = apply(store, session_id=None, operations=[], principal=principal)
        assert store.get_state(r.session_id).user_id == "user-1"

    def test_이미_있는_user_id는_덮어쓰지_않는다(self, store):
        principal = Principal(user_id="user-원래주인", is_anonymous=True)
        first = apply(store, session_id=None, operations=[], principal=principal)

        # 같은 사람이 다시 요청해도(예: is_anonymous만 바뀌는 정식 로그인 전환)
        # user_id는 그대로 유지된다 — 소유권 대조(D-073)를 통과한 뒤의 attach_user_id
        # 동작만 확인한다. 다른 사람의 거부는 TestSessionOwnership에서 검증한다.
        apply(
            store,
            session_id=first.session_id,
            operations=[],
            principal=Principal(user_id="user-원래주인", is_anonymous=False),
        )

        assert store.get_state(first.session_id).user_id == "user-원래주인"

    def test_confirmed_False_경로에서도_user_id가_저장된다(self, store):
        principal = Principal(user_id="user-1", is_anonymous=True)
        r = apply(
            store, session_id=None, confirmed=False, operations=[], principal=principal
        )
        assert store.get_state(r.session_id).user_id == "user-1"


class TestSessionOwnership:
    """D-063 결정 2 후속(D-073) — session_id만으로 남의 세션에 접근하지 못하게 막는다.

    apply()는 세션 확보 직후, get_session_context()/delete_session()은
    조회·삭제 직전에 각각 session.verify_ownership()을 호출한다.
    """

    def test_같은_user_id는_통과한다(self, store):
        principal = Principal(user_id="user-1", is_anonymous=True)
        first = apply(store, session_id=None, operations=[], principal=principal)

        r = apply(
            store,
            session_id=first.session_id,
            operations=[],
            principal=principal,
        )

        assert r.session_id == first.session_id

    def test_다른_user_id는_apply에서_거부된다(self, store):
        owner = Principal(user_id="user-원래주인", is_anonymous=True)
        stranger = Principal(user_id="user-다른사람", is_anonymous=True)
        first = apply(store, session_id=None, operations=[], principal=owner)

        with pytest.raises(SessionOwnershipError):
            apply(store, session_id=first.session_id, operations=[], principal=stranger)

    def test_principal이_없으면_기존_게스트_흐름대로_통과한다(self, store):
        owner = Principal(user_id="user-원래주인", is_anonymous=True)
        first = apply(store, session_id=None, operations=[], principal=owner)

        r = apply(store, session_id=first.session_id, operations=[], principal=None)

        assert r.session_id == first.session_id

    def test_user_id가_비어있는_세션은_통과한다(self, store):
        """아직 아무도 신원을 붙이지 않은 세션 — 거부 대상이 아니라
        attach_user_id()가 채울 대상이다."""
        first = apply(store, session_id=None, operations=[], principal=None)
        principal = Principal(user_id="user-1", is_anonymous=True)

        r = apply(store, session_id=first.session_id, operations=[], principal=principal)

        assert r.session_id == first.session_id
        assert store.get_state(first.session_id).user_id == "user-1"

    def test_get_session_context도_다른_user_id는_거부한다(self, store):
        owner = Principal(user_id="user-원래주인", is_anonymous=True)
        stranger = Principal(user_id="user-다른사람", is_anonymous=True)
        first = apply(store, session_id=None, operations=[], principal=owner)

        with pytest.raises(SessionOwnershipError):
            svc.get_session_context(first.session_id, store=store, principal=stranger)

    def test_delete_session도_다른_user_id는_거부한다(self, store):
        owner = Principal(user_id="user-원래주인", is_anonymous=True)
        stranger = Principal(user_id="user-다른사람", is_anonymous=True)
        first = apply(store, session_id=None, operations=[], principal=owner)

        with pytest.raises(SessionOwnershipError):
            svc.delete_session(first.session_id, store=store, principal=stranger)

        # 거부됐으니 세션은 그대로 남아 있어야 한다.
        assert store.get_state(first.session_id) is not None


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

    def test_shown_recommendations도_마지막_실행_기준_전체_항목이다(self, store):
        """COMPARE 데이터 출처 A안(2026-08-11): shown_place_ids와 같은 기준
        (마지막 run_id, rank 순)으로 distance_km 등 전체 Feature 스냅샷을
        함께 반환한다."""
        first = apply(store, session_id=None, operations=[])
        sid = first.session_id
        svc.record_recommendation(
            svc.RecordRecommendationRequest(
                session_id=sid,
                run_id=first.run_id,
                recommended=[
                    svc.RecommendedPlace(
                        place_id="A", rank=1, distance_km=0.5,
                        remaining_minutes=30, environment_type="indoor",
                    ),
                ],
            ),
            store=store,
        )

        second = apply(store, session_id=sid, operations=[])
        svc.record_recommendation(
            svc.RecordRecommendationRequest(
                session_id=sid,
                run_id=second.run_id,
                recommended=[
                    svc.RecommendedPlace(
                        place_id="D", rank=1, distance_km=1.2,
                        remaining_minutes=90, environment_type="outdoor",
                    ),
                    svc.RecommendedPlace(
                        place_id="E", rank=2, distance_km=2.4,
                        remaining_minutes=None, environment_type="unknown",
                    ),
                ],
            ),
            store=store,
        )

        ctx = svc.get_session_context(sid, store=store)

        assert [item.place_id for item in ctx.shown_recommendations] == ["D", "E"]
        first_item = ctx.shown_recommendations[0]
        assert first_item.distance_km == 1.2
        assert first_item.remaining_minutes == 90
        assert first_item.environment_type == "outdoor"
        second_item = ctx.shown_recommendations[1]
        assert second_item.distance_km == 2.4
        assert second_item.remaining_minutes is None
        assert second_item.environment_type == "unknown"

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

    def test_일정_세부_필드가_함께_저장된다(self, store):
        """SCHEDULE-06: RecommendedPlace의 SCHEDULE 전용 선택 필드가
        RecommendedItem까지 그대로 전달·저장되는지 확인한다."""
        r = apply(store, session_id=None, operations=[])
        svc.record_recommendation(
            svc.RecordRecommendationRequest(
                session_id=r.session_id,
                run_id=r.run_id,
                recommended=[
                    svc.RecommendedPlace(
                        place_id="A",
                        rank=1,
                        estimated_arrival="14:00",
                        estimated_duration_min=60,
                        travel_to_next_min=15,
                        reason="테스트용 배치 이유",
                    )
                ],
            ),
            store=store,
        )

        history = store.get_history(r.session_id)
        assert history is not None
        item = history.recommended[-1]
        assert item.place_id == "A"
        assert item.estimated_arrival == "14:00"
        assert item.estimated_duration_min == 60
        assert item.travel_to_next_min == 15
        assert item.reason == "테스트용 배치 이유"

    def test_필드를_생략하면_None으로_저장된다(self, store):
        """기존 RECOMMEND/MODIFY 호출(필드 생략)은 회귀 없이 그대로 동작한다."""
        r = apply(store, session_id=None, operations=[])
        record(store, r.session_id, r.run_id, [("A", 1)])

        history = store.get_history(r.session_id)
        item = history.recommended[-1]
        assert item.estimated_arrival is None
        assert item.estimated_duration_min is None
        assert item.travel_to_next_min is None
        assert item.reason is None
        assert item.distance_km is None
        assert item.remaining_minutes is None
        assert item.environment_type is None

    def test_COMPARE_Feature_스냅샷이_함께_저장된다(self, store):
        """COMPARE 데이터 출처 A안(2026-08-11): RecommendedPlace의 COMPARE 전용
        선택 필드가 RecommendedItem까지 그대로 전달·저장되는지 확인한다."""
        r = apply(store, session_id=None, operations=[])
        svc.record_recommendation(
            svc.RecordRecommendationRequest(
                session_id=r.session_id,
                run_id=r.run_id,
                recommended=[
                    svc.RecommendedPlace(
                        place_id="A",
                        rank=1,
                        distance_km=0.42,
                        remaining_minutes=75,
                        environment_type="indoor",
                    )
                ],
            ),
            store=store,
        )

        history = store.get_history(r.session_id)
        assert history is not None
        item = history.recommended[-1]
        assert item.place_id == "A"
        assert item.distance_km == 0.42
        assert item.remaining_minutes == 75
        assert item.environment_type == "indoor"


# ================================================================ TP-82

class TestRecordClosedExclusions:
    """영업 종료 후보가 노출 이력 없이 매 회차 재수집되던 문제(TP-82) 검증.

    D의 하드 필터가 걸러낸 place_id를 recommended/rejected와 별도로 기록해도,
    다음 회차 excluded_place_ids에는 셋 다 합쳐져야 한다(get_exclusion_place_ids
    변경).
    """

    def test_기록_건수를_반환한다(self, store):
        r = apply(store, session_id=None, operations=[])
        res = svc.record_closed_exclusions(
            svc.RecordClosedExclusionsRequest(
                session_id=r.session_id, run_id=r.run_id, place_ids=["A", "B"]
            ),
            store=store,
        )

        assert res.recorded == 2

    def test_빈_목록도_오류가_아니다(self, store):
        r = apply(store, session_id=None, operations=[])
        res = svc.record_closed_exclusions(
            svc.RecordClosedExclusionsRequest(
                session_id=r.session_id, run_id=r.run_id, place_ids=[]
            ),
            store=store,
        )
        assert res.recorded == 0

    def test_기록한_장소가_다음_회차_제외_목록에_들어간다(self, store):
        first = apply(store, session_id=None, operations=[])
        svc.record_closed_exclusions(
            svc.RecordClosedExclusionsRequest(
                session_id=first.session_id, run_id=first.run_id, place_ids=["A"]
            ),
            store=store,
        )

        second = apply(store, session_id=first.session_id, operations=[])
        assert "A" in second.excluded_place_ids

    def test_노출_이력과_구분해서_저장된다(self, store):
        """closed_excluded는 recommended와 다른 리스트다 — 섞이면 "노출했다"로
        잘못 취급되어 COMPARE의 "첫 번째"가 실제로 안 보여준 장소를 가리키게
        된다."""
        r = apply(store, session_id=None, operations=[])
        svc.record_closed_exclusions(
            svc.RecordClosedExclusionsRequest(
                session_id=r.session_id, run_id=r.run_id, place_ids=["A"]
            ),
            store=store,
        )

        history = store.get_history(r.session_id)
        assert history is not None
        assert [item.place_id for item in history.closed_excluded] == ["A"]
        assert history.recommended == []

    def test_recommended_초기화_시_함께_비워진다(self, store):
        """clear_recommended()(history reset)는 closed_excluded도 함께 비운다 —
        폐점 여부는 시각에 따라 바뀌는 사실이라 새 검색 컨텍스트까지 영구히
        제외할 근거가 아니다."""
        first = apply(store, session_id=None, operations=[])
        svc.record_closed_exclusions(
            svc.RecordClosedExclusionsRequest(
                session_id=first.session_id, run_id=first.run_id, place_ids=["A"]
            ),
            store=store,
        )

        reset = apply(
            store,
            session_id=first.session_id,
            operations=[],
            reset_scope="history",
        )

        assert "A" not in reset.excluded_place_ids


class TestRecordHistoryUserId:
    """TP-101 3단계, D-063 — recommendation_histories.user_id도 AgentState와
    같은 규칙(채우되 덮어쓰지 않음)으로 record_recommendation/
    record_closed_exclusions/apply()의 rejected_places 경로 세 곳 모두에서
    연결되는지 확인한다."""

    def test_record_recommendation이_user_id를_채운다(self, store):
        r = apply(store, session_id=None, operations=[])
        principal = Principal(user_id="user-1", is_anonymous=True)

        svc.record_recommendation(
            svc.RecordRecommendationRequest(
                session_id=r.session_id,
                run_id=r.run_id,
                recommended=[svc.RecommendedPlace(place_id="A", rank=1)],
            ),
            store=store,
            principal=principal,
        )

        assert store.get_history(r.session_id).user_id == "user-1"

    def test_record_closed_exclusions이_user_id를_채운다(self, store):
        r = apply(store, session_id=None, operations=[])
        principal = Principal(user_id="user-1", is_anonymous=True)

        svc.record_closed_exclusions(
            svc.RecordClosedExclusionsRequest(
                session_id=r.session_id, run_id=r.run_id, place_ids=["A"]
            ),
            store=store,
            principal=principal,
        )

        assert store.get_history(r.session_id).user_id == "user-1"

    def test_apply의_rejected_places_경로도_user_id를_채운다(self, store):
        principal = Principal(user_id="user-1", is_anonymous=True)

        r = apply(
            store,
            session_id=None,
            operations=[],
            rejected_places=[{"place_id": "A"}],
            principal=principal,
        )

        assert store.get_history(r.session_id).user_id == "user-1"

    def test_이미_있는_history_user_id는_덮어쓰지_않는다(self, store):
        r = apply(store, session_id=None, operations=[])
        svc.record_recommendation(
            svc.RecordRecommendationRequest(
                session_id=r.session_id,
                run_id=r.run_id,
                recommended=[svc.RecommendedPlace(place_id="A", rank=1)],
            ),
            store=store,
            principal=Principal(user_id="user-원래주인", is_anonymous=True),
        )

        svc.record_closed_exclusions(
            svc.RecordClosedExclusionsRequest(
                session_id=r.session_id, run_id=r.run_id, place_ids=["B"]
            ),
            store=store,
            principal=Principal(user_id="user-다른사람", is_anonymous=True),
        )

        assert store.get_history(r.session_id).user_id == "user-원래주인"


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

    # ---------------------------------------------------- PR #188

    def test_기존_세션은_재확인_시각이_null이다(self, store):
        r = apply(store, session_id=None, operations=[])
        assert r.api_context.gps_location_confirmed_at is None

    def test_재확인_시각을_명시적으로_전달하면_저장된다(self, store):
        r = apply(store, session_id=None, operations=[])
        confirmed_at = now_kst()

        res = svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id=r.session_id,
                gps_location="37.5665,126.9780",
                gps_location_confirmed_at=confirmed_at,
            ),
            store=store,
        )

        assert res is not None
        assert res.api_context.gps_location_confirmed_at == confirmed_at

    def test_gps_location만_갱신하면_재확인_시각은_그대로다(self, store):
        """"N분 전 위치로 계속"처럼 재확인 없이 위치만 갱신되는 경우를 흉내낸다
        — gps_location_updated_at(기술적 TTL)과 gps_location_confirmed_at
        (사용자 재확인)이 혼용되면 안 된다."""
        r = apply(store, session_id=None, operations=[])
        confirmed_at = now_kst()

        svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id=r.session_id,
                gps_location="37.5665,126.9780",
                gps_location_confirmed_at=confirmed_at,
            ),
            store=store,
        )
        res = svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id=r.session_id, gps_location="37.6,127.0"
            ),
            store=store,
        )

        assert res is not None
        assert res.api_context.gps_location == "37.6,127.0"
        assert res.api_context.gps_location_confirmed_at == confirmed_at

    def test_재확인_시각을_생략하면_현재시각으로_채워진다(self, store):
        """gps_location_updated_at과 동일한 관례 — 필드는 전달했지만 값을
        안 채우면(None) now로 채운다."""
        r = apply(store, session_id=None, operations=[])

        res = svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id=r.session_id,
                gps_location="37.5665,126.9780",
                gps_location_confirmed_at=None,
            ),
            store=store,
        )

        assert res is not None
        assert res.api_context.gps_location_confirmed_at is not None

    def test_get_session_context에도_재확인_시각이_포함된다(self, store):
        r = apply(store, session_id=None, operations=[])
        confirmed_at = now_kst()

        svc.update_api_context(
            svc.UpdateApiContextRequest(
                session_id=r.session_id,
                gps_location="37.5665,126.9780",
                gps_location_confirmed_at=confirmed_at,
            ),
            store=store,
        )
        ctx = svc.get_session_context(r.session_id, store=store)

        assert ctx.api_context.gps_location_confirmed_at == confirmed_at


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


def _place_ambiguous_context() -> PendingInfoContext:
    return PendingInfoContext(
        question_type="parking",
        place_context="explicit",
        specific_question="주차장 정보",
        visit_time=None,
    )


def test_set_pending_info_context_stores_and_exposes_context() -> None:
    store = InMemoryStateStore()
    session_id = _session(store)

    result = svc.set_pending_info_context(
        svc.SetPendingInfoContextRequest(
            session_id=session_id, context=_place_ambiguous_context()
        ),
        store=store,
    )

    assert result is not None
    assert result.pending_info_context == _place_ambiguous_context()
    context = svc.get_session_context(session_id, store=store)
    assert context.pending_info_context == _place_ambiguous_context()


def test_set_pending_info_context_clears_with_none() -> None:
    store = InMemoryStateStore()
    session_id = _session(store)
    svc.set_pending_info_context(
        svc.SetPendingInfoContextRequest(
            session_id=session_id, context=_place_ambiguous_context()
        ),
        store=store,
    )

    svc.set_pending_info_context(
        svc.SetPendingInfoContextRequest(session_id=session_id, context=None), store=store
    )

    assert svc.get_session_context(session_id, store=store).pending_info_context is None


def test_set_pending_info_context_returns_none_for_missing_session() -> None:
    store = InMemoryStateStore()

    result = svc.set_pending_info_context(
        svc.SetPendingInfoContextRequest(session_id="sess_missing", context=None), store=store
    )

    assert result is None


def test_set_pending_clarification_keeps_pending_info_context_for_place_ambiguous() -> None:
    """code가 place_ambiguous 그대로면 저장해둔 원래 질문을 건드리지 않는다."""
    store = InMemoryStateStore()
    session_id = _session(store)
    svc.set_pending_info_context(
        svc.SetPendingInfoContextRequest(
            session_id=session_id, context=_place_ambiguous_context()
        ),
        store=store,
    )

    svc.set_pending_clarification(
        svc.SetPendingClarificationRequest(session_id=session_id, code="place_ambiguous"),
        store=store,
    )

    context = svc.get_session_context(session_id, store=store)
    assert context.pending_info_context == _place_ambiguous_context()


def test_set_pending_clarification_clears_pending_info_context_when_code_changes() -> None:
    """다른 되묻기 코드로 바뀌거나 지워지면 pending_info_context도 같이 지워진다
    — place_ambiguous일 때만 의미가 있는 값이라 따로 안 챙기면 다음 턴에
    엉뚱한 질문(주차 등)으로 새는 걸 막는다."""
    store = InMemoryStateStore()
    session_id = _session(store)
    svc.set_pending_info_context(
        svc.SetPendingInfoContextRequest(
            session_id=session_id, context=_place_ambiguous_context()
        ),
        store=store,
    )

    svc.set_pending_clarification(
        svc.SetPendingClarificationRequest(session_id=session_id, code="location_required"),
        store=store,
    )

    context = svc.get_session_context(session_id, store=store)
    assert context.pending_clarification == "location_required"
    assert context.pending_info_context is None
