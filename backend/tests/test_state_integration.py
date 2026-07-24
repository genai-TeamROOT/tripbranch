"""state_transform.transform() + B의 실제 apply()를 이어붙인 다중 턴 통합 테스트.

tests/state/test_service.py::TestMultiTurnScenario::test_전체_대화_흐름과 같은 흐름
(1턴 추천 → 2턴 REJECT_ALL → 3턴 조건 변경)을, LLMOutput → transform() → apply()로
재현했을 때 같은 결과가 나오는지 확인한다. 4턴은 그 테스트의 "history reset" 대신
이번 구현이 실제로 지원하는 시나리오(RECOMMEND의 reset_scope=soft)로 검증한다 —
CHANGE_CONDITION은 항상 현재 노출 장소를 rejected로 기록하므로(reason=other),
원본 테스트의 "history reset이 노출 이력만 지운다" 뉘앙스는 REJECT_ALL 없이 조건만
바뀌는 경우에는 그대로 관찰되지 않는다(둘 다 이번 구현에서 의도된 동작이다).
"""

from __future__ import annotations

from app.schemas import (
    Intent,
    LLMOutput,
    ModifyPayload,
    ModifyType,
    OutputStatus,
    RecommendPayload,
    UserConditions,
)
from app.services.interpret.state_transform import transform
from app.state.service import (
    RecommendedPlace,
    RecordRecommendationRequest,
    apply,
    get_session_context,
    record_recommendation,
)
from app.state.store import InMemoryStateStore


def test_multi_turn_flow_matches_raw_state_service_scenario() -> None:
    store = InMemoryStateStore()

    # 1턴: RECOMMEND
    ctx1 = get_session_context(None, store=store)
    llm1 = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(
            conditions=UserConditions(
                search_center="경복궁", place_types=["restaurant"], place_tags=["카페"]
            )
        ),
    )
    req1 = transform(llm1, ctx1, "경복궁 근처 카페 추천해줘")
    r1 = apply(req1, store=store)
    sid = r1.session_id
    record_recommendation(
        RecordRecommendationRequest(
            session_id=sid,
            run_id=r1.run_id,
            recommended=[
                RecommendedPlace(place_id="A", rank=1),
                RecommendedPlace(place_id="B", rank=2),
                RecommendedPlace(place_id="C", rank=3),
            ],
        ),
        store=store,
    )

    assert r1.condition_version == 1
    assert r1.user_conditions.search_center == "경복궁"

    # 2턴: MODIFY REJECT_ALL — 조건 유지, 이력 누적 (원본 테스트 t2와 동일)
    ctx2 = get_session_context(sid, store=store)
    assert ctx2.shown_place_ids == ["A", "B", "C"]
    llm2 = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(modify_type=ModifyType.REJECT_ALL),
    )
    req2 = transform(llm2, ctx2, "다른 곳 보여줘")
    r2 = apply(req2, store=store)
    record_recommendation(
        RecordRecommendationRequest(
            session_id=sid,
            run_id=r2.run_id,
            recommended=[
                RecommendedPlace(place_id="D", rank=1),
                RecommendedPlace(place_id="E", rank=2),
            ],
        ),
        store=store,
    )

    assert r2.condition_changed is False
    assert r2.condition_version == 1
    assert r2.excluded_place_ids == ["A", "B", "C"]

    # 3턴: MODIFY CHANGE_CONDITION(budget=free) — 조건 병합 + 직전 노출분 자동 제외
    # (원본 테스트는 D만 명시적으로 거절하지만, 이번 구현은 CHANGE_CONDITION 시 직전
    # 노출 전체(D, E)를 reason=other로 제외 처리한다 — 설계상 의도된 차이)
    ctx3 = get_session_context(sid, store=store)
    changes = ctx3.user_conditions.model_copy(update={"budget": "free"})
    llm3 = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(
            modify_type=ModifyType.CHANGE_CONDITION,
            condition_changes=UserConditions(**changes.model_dump()),
            changed_fields=["budget"],
        ),
    )
    req3 = transform(llm3, ctx3, "무료인 곳으로")
    r3 = apply(req3, store=store)

    assert r3.condition_version == 2
    assert r3.user_conditions.search_center == "경복궁"  # 이전 조건 유지
    assert r3.user_conditions.budget == "free"
    assert set(r3.excluded_place_ids) == {"A", "B", "C", "D", "E"}

    # 4턴: 새 RECOMMEND — reset_scope=soft로 조건은 재생성되지만 이력은 유지된다
    # (이번 구현의 설계 결정: conditions-schema.md §6 "새 RECOMMEND → user_conditions 재생성")
    ctx4 = get_session_context(sid, store=store)
    llm4 = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(
            conditions=UserConditions(place_types=["cultural_facility"], place_tags=["박물관"])
        ),
    )
    req4 = transform(llm4, ctx4, "박물관 가고 싶어")
    assert req4.reset_scope == "soft"
    r4 = apply(req4, store=store)

    assert r4.user_conditions.budget is None  # soft reset으로 조건 초기화
    assert r4.user_conditions.place_types == ["cultural_facility"]
    assert r4.session_id == sid  # soft는 세션을 새로 만들지 않는다
    assert set(r4.excluded_place_ids) == {"A", "B", "C", "D", "E"}  # 이력은 유지
