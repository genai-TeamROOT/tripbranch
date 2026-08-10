"""state_transform.transform()의 LLMOutput → StateApplyRequest 변환 회귀 테스트.

docs/design/test-cases.md의 TC-07~09와 conditions-schema.md §5 예시5(place_tags 정리)를
재현한다.
"""

from __future__ import annotations

from app.providers.gemini_prompts import PROMPT_VERSION
from app.schemas import (
    ConcentrationIntent,
    Environment,
    Intent,
    LLMOutput,
    ModifyPayload,
    ModifyType,
    OutputStatus,
    RecommendPayload,
    UserConditions,
    WeatherIntent,
)
from app.services.interpret.state_transform import transform
from app.state.schema import UserConditions as StateUserConditions
from app.state.service import SessionContextResponse


def _context(
    *,
    session_id: str = "sess_1",
    shown_place_ids: list[str] | None = None,
    user_conditions: StateUserConditions | None = None,
    pending_clarification: str | None = None,
) -> SessionContextResponse:
    return SessionContextResponse(
        session_id=session_id,
        session_exists=True,
        has_recommendation=bool(shown_place_ids),
        recommended_count=len(shown_place_ids or []),
        shown_place_ids=shown_place_ids or [],
        user_conditions=user_conditions or StateUserConditions(),
        pending_clarification=pending_clarification,
    )


def test_recommend_resets_soft_and_updates_all_set_fields() -> None:
    llm_output = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(
            conditions=UserConditions(
                search_center="경복궁",
                place_types=["restaurant"],
                place_tags=["카페"],
            )
        ),
    )

    request = transform(llm_output, _context(), "경복궁 근처 카페 추천해줘")

    assert request.reset_scope == "soft"
    ops = {(op.op, op.field): op.value for op in request.operations}
    assert ops[("Update", "search_center")] == "경복궁"
    assert ops[("Update", "place_types")] == ["restaurant"]
    assert ops[("Update", "place_tags")] == ["카페"]
    assert request.confirmed is True
    assert request.intent == "RECOMMEND"
    assert request.prompt_version == PROMPT_VERSION


def test_schedule_merges_conditions_same_as_recommend() -> None:
    """SCHEDULE-04: orchestrator.py가 SCHEDULE에도 llm_output.recommend를 채워주므로
    (docs/design/int-07-schedule.md 4절 "조건 병합 (기존과 동일)"), RECOMMEND와
    같은 분기를 타야 한다 — 137번째 줄 조건에 SCHEDULE도 포함됐는지 확인."""
    llm_output = LLMOutput(
        intent=Intent.SCHEDULE,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(
            conditions=UserConditions(search_center="경복궁", place_tags=["카페"])
        ),
    )

    request = transform(llm_output, _context(), "경복궁 근처에서 반나절 코스 짜줘")

    assert request.intent == "SCHEDULE"
    ops = {(op.op, op.field): op.value for op in request.operations}
    assert ops[("Update", "search_center")] == "경복궁"
    assert ops[("Update", "place_tags")] == ["카페"]
    assert request.reset_scope == "soft"
    assert request.confirmed is True


def test_recommend_serializes_int_fields_as_int_not_str() -> None:
    """_serialize() 회귀: max_travel_time/time_available은 str()로 감싸지지 않는다.

    B(agent-state-contract-v1.md §2.2)가 int 타입을 기대하므로, str "30"으로
    가면 type_mismatch로 조용히 드롭된다("가까운 곳으로"가 반영 안 되던 버그).
    """
    llm_output = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(
            conditions=UserConditions(
                search_center="경복궁", max_travel_time=30, time_available=120
            )
        ),
    )

    request = transform(llm_output, _context(), "가까운 곳으로")

    ops = {(op.op, op.field): op.value for op in request.operations}
    assert ops[("Update", "max_travel_time")] == 30
    assert isinstance(ops[("Update", "max_travel_time")], int)
    assert ops[("Update", "time_available")] == 120
    assert isinstance(ops[("Update", "time_available")], int)


def test_recommend_uses_add_for_exclude_tags_and_special_requirements() -> None:
    """exclude_tags/special_requirements는 Add/Remove만 허용되므로(§2.2) Update가
    아니라 Add로 나가야 한다 — 안 그러면 unsupported_operation으로 드롭된다."""
    llm_output = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(
            conditions=UserConditions(
                search_center="경복궁",
                exclude_tags=["박물관"],
                special_requirements=["주차"],
            )
        ),
    )

    request = transform(llm_output, _context(), "박물관 제외하고 카페 추천해줘")

    ops = {(op.op, op.field): op.value for op in request.operations}
    assert ops[("Add", "exclude_tags")] == ["박물관"]
    assert ops[("Add", "special_requirements")] == ["주차"]
    assert ("Update", "exclude_tags") not in ops
    assert ("Update", "special_requirements") not in ops


def test_recommend_still_uses_update_for_place_types_and_place_tags() -> None:
    """place_types(Update/Remove만 허용)·place_tags(Add/Update/Remove 허용)는
    exclude_tags/special_requirements 수정에 휩쓸려 Add로 바뀌면 안 된다."""
    llm_output = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(
            conditions=UserConditions(place_types=["restaurant"], place_tags=["카페"])
        ),
    )

    request = transform(llm_output, _context(), "카페 추천해줘")

    ops = {(op.op, op.field): op.value for op in request.operations}
    assert ops[("Update", "place_types")] == ["restaurant"]
    assert ops[("Update", "place_tags")] == ["카페"]


def test_recommend_skips_null_and_empty_fields() -> None:
    llm_output = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(conditions=UserConditions()),
    )

    request = transform(llm_output, _context(), "추천해줘")

    assert request.operations == []
    assert request.reset_scope == "soft"


def test_recommend_without_new_location_preserves_existing_search_center() -> None:
    """새 추천에서 장소 유형만 바꿔도 기존 목적지는 soft reset 뒤 복원한다."""
    llm_output = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(
            conditions=UserConditions(place_types=["restaurant"], place_tags=["카페"])
        ),
    )
    context = _context(user_conditions=StateUserConditions(search_center="대학로"))

    request = transform(llm_output, context, "카페 추천해줘")

    ops = {(op.op, op.field): op.value for op in request.operations}
    assert request.reset_scope == "soft"
    assert ops[("Update", "search_center")] == "대학로"
    assert ops[("Update", "place_tags")] == ["카페"]


def test_recommend_with_new_search_center_does_not_restore_previous_center() -> None:
    llm_output = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(conditions=UserConditions(search_center="광화문")),
    )
    context = _context(user_conditions=StateUserConditions(search_center="대학로"))

    request = transform(llm_output, context, "광화문 근처 추천해줘")

    ops = {(op.op, op.field): op.value for op in request.operations}
    assert ops[("Update", "search_center")] == "광화문"


def test_tc07_reject_all_has_no_operations_and_marks_not_interested() -> None:
    llm_output = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(modify_type=ModifyType.REJECT_ALL),
    )
    context = _context(shown_place_ids=["A", "B", "C"])

    request = transform(llm_output, context, "다른 곳 보여줘")

    assert request.operations == []
    assert [(r.place_id, r.reason_code) for r in request.rejected_places] == [
        ("A", "not_interested"),
        ("B", "not_interested"),
        ("C", "not_interested"),
    ]
    assert request.reset_scope is None


def test_tc08_change_condition_budget_update_triggers_reset_scope_history() -> None:
    """CHANGE_CONDITION은 직전 노출분을 rejected로 영구 제외하지 않는다.

    대신 reset_scope="history"로 recommended만 비워서, 조건이 되돌아오면 다시
    노출될 수 있게 한다(거절 이력은 그대로 유지 — B의 history reset이 보장).
    """
    current = StateUserConditions(search_center="경복궁", place_types=["restaurant"])
    context = _context(shown_place_ids=["A", "B", "C"], user_conditions=current)
    changes = UserConditions(search_center="경복궁", place_types=["restaurant"], budget="free")
    llm_output = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(
            modify_type=ModifyType.CHANGE_CONDITION,
            condition_changes=changes,
            changed_fields=["budget"],
        ),
    )

    request = transform(llm_output, context, "무료인 곳으로")

    assert len(request.operations) == 1
    assert request.operations[0].op == "Update"
    assert request.operations[0].field == "budget"
    assert request.operations[0].value == "free"
    assert request.rejected_places == []
    assert request.reset_scope == "history"


def test_tc09_search_center_change_triggers_reset_scope_history() -> None:
    current = StateUserConditions(search_center="경복궁")
    context = _context(shown_place_ids=["A", "B", "C"], user_conditions=current)
    changes = UserConditions(search_center="인사동")
    llm_output = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(
            modify_type=ModifyType.CHANGE_CONDITION,
            condition_changes=changes,
            changed_fields=["search_center"],
        ),
    )

    request = transform(llm_output, context, "인사동 근처로 바꿔줘")

    assert request.reset_scope == "history"
    assert request.operations[0].field == "search_center"
    assert request.operations[0].value == "인사동"


def test_change_condition_clears_field_with_remove_not_update_null() -> None:
    """budget: null(해제 의도)은 Update(value=None)이 아니라 Remove여야 한다.

    B의 operations.py는 Update에 value=None을 null_value 오류로 거부하기 때문.
    """
    current = StateUserConditions(budget="free")
    context = _context(user_conditions=current)
    changes = UserConditions(budget=None)
    llm_output = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(
            modify_type=ModifyType.CHANGE_CONDITION,
            condition_changes=changes,
            changed_fields=["budget"],
        ),
    )

    request = transform(llm_output, context, "가격 상관없어")

    assert len(request.operations) == 1
    assert request.operations[0].op == "Remove"
    assert request.operations[0].field == "budget"


def test_change_condition_ignores_unlisted_fields_even_if_present_in_payload() -> None:
    """changed_fields에 없는 필드는 condition_changes에 값이 있어도 Keep(연산 생성 안 함)."""
    current = StateUserConditions(search_center="경복궁", budget="free")
    context = _context(user_conditions=current)
    changes = UserConditions(search_center="경복궁", budget="free", environment="indoor")
    llm_output = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(
            modify_type=ModifyType.CHANGE_CONDITION,
            condition_changes=changes,
            changed_fields=["environment"],
        ),
    )

    request = transform(llm_output, context, "실내로 바꿔줘")

    assert len(request.operations) == 1
    assert request.operations[0].field == "environment"


def test_place_types_replace_removes_orphaned_place_tags() -> None:
    """conditions-schema.md §5 예시5: place_types 교체 시 소속 안 되는 place_tags를 Remove."""
    current = StateUserConditions(
        place_types=["cultural_facility", "restaurant"],
        place_tags=["박물관", "카페"],
    )
    context = _context(shown_place_ids=["X"], user_conditions=current)
    changes = UserConditions(place_types=["cultural_facility", "shopping"])
    llm_output = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(
            modify_type=ModifyType.CHANGE_CONDITION,
            condition_changes=changes,
            changed_fields=["place_types"],
        ),
    )

    request = transform(llm_output, context, "음식점 빼고 쇼핑으로")

    ops = {op.field: op for op in request.operations}
    assert ops["place_types"].op == "Update"
    assert ops["place_types"].value == ["cultural_facility", "shopping"]
    assert ops["place_tags"].op == "Remove"
    assert ops["place_tags"].value == ["카페"]


def test_place_types_replace_skips_cleanup_when_llm_already_sent_place_tags() -> None:
    current = StateUserConditions(
        place_types=["cultural_facility", "restaurant"],
        place_tags=["박물관", "카페"],
    )
    context = _context(user_conditions=current)
    changes = UserConditions(place_types=["shopping"], place_tags=[])
    llm_output = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(
            modify_type=ModifyType.CHANGE_CONDITION,
            condition_changes=changes,
            changed_fields=["place_types", "place_tags"],
        ),
    )

    request = transform(llm_output, context, "쇼핑만 할래")

    fields = [op.field for op in request.operations]
    assert fields.count("place_tags") == 1  # 자동 정리로 인한 중복 Remove가 없어야 한다


def test_reset_scope_phrase_detection() -> None:
    context = _context(shown_place_ids=["A"])
    llm_output = LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(modify_type=ModifyType.REJECT_ALL),
    )

    assert transform(llm_output, context, "처음부터 다시 해줘").reset_scope == "history"
    assert transform(llm_output, context, "새로 시작할래").reset_scope == "full"
    assert transform(llm_output, context, "조건 다시 정할게").reset_scope == "soft"
    assert transform(llm_output, context, "그냥 다른 곳 보여줘").reset_scope is None


def test_non_recommend_non_modify_intents_have_no_operations() -> None:
    from app.schemas import (
        CompareCriteria,
        ComparePayload,
        GeneralPayload,
        GeneralTopic,
        InfoPayload,
        PlaceContext,
        QuestionType,
    )

    context = _context()
    info_output = LLMOutput(
        intent=Intent.INFO,
        status=OutputStatus.COMPLETE,
        info=InfoPayload(
            place_name="경복궁",
            place_context=PlaceContext.EXPLICIT,
            question_type=QuestionType.OPERATING_HOURS,
        ),
    )
    compare_output = LLMOutput(
        intent=Intent.COMPARE,
        status=OutputStatus.COMPLETE,
        compare=ComparePayload(targets="all", criteria=CompareCriteria.DISTANCE),
    )
    general_output = LLMOutput(
        intent=Intent.GENERAL,
        status=OutputStatus.COMPLETE,
        general=GeneralPayload(topic=GeneralTopic.PLACE_KNOWLEDGE, original_question="?"),
    )

    for output, text in (
        (info_output, "경복궁 오늘 열어?"),
        (compare_output, "어디가 좋아?"),
        (general_output, "경복궁 역사 알려줘"),
    ):
        request = transform(output, context, text)
        assert request.operations == []
        assert request.rejected_places == []
        assert request.reset_scope is None


def _recommend(**conditions) -> LLMOutput:
    return LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(conditions=UserConditions(**conditions)),
    )


def test_recommend_answering_clarification_keeps_previous_conditions() -> None:
    """되묻기 답변은 새 요청이 아니므로 조건을 초기화하지 않는다.

    1턴 "근처 카페나 박물관 추천해줘"(위치 없음) → C가 location_required로 되물음
    2턴 "경복궁 근처" → 위치만 채워지고 place_tags는 유지되어야 한다.
    """
    request = transform(
        _recommend(search_center="경복궁"),
        _context(pending_clarification="location_required"),
        "경복궁 근처",
    )

    assert request.reset_scope is None
    ops = {(op.op, op.field): op.value for op in request.operations}
    assert ops[("Update", "search_center")] == "경복궁"
    # 언급하지 않은 필드는 Operation 자체가 없어 B에서 자동 유지된다.
    assert ("Update", "place_tags") not in ops


def test_recommend_answering_clarification_keeps_prior_intents_on_default_values() -> None:
    """위치 되묻기 답변의 NO_MENTION/IGNORE/ANY는 기존 의도를 해제하지 않는다.

    environment는 Environment에 NO_MENTION 상당 값이 없어 "언급 안 함"이 ANY로 오는데,
    이걸 그대로 Update하면 앞 턴의 indoor(비를 피하려던 조건)가 사라진다.
    """
    request = transform(
        _recommend(
            search_center="경복궁",
            weather_intent=WeatherIntent.NO_MENTION,
            concentration_intent=ConcentrationIntent.IGNORE,
            environment=Environment.ANY,
        ),
        _context(pending_clarification="location_required"),
        "경복궁 근처에서",
    )

    ops = {(op.op, op.field): op.value for op in request.operations}
    assert ops[("Update", "search_center")] == "경복궁"
    assert ("Update", "weather_intent") not in ops
    assert ("Update", "concentration_intent") not in ops
    assert ("Update", "environment") not in ops


def test_recommend_answering_clarification_still_applies_explicit_environment() -> None:
    """되묻기 답변이라도 실내/실외를 명시하면 그 값은 적용한다."""
    request = transform(
        _recommend(search_center="경복궁", environment=Environment.OUTDOOR),
        _context(pending_clarification="location_required"),
        "경복궁 근처 야외로",
    )

    ops = {(op.op, op.field): op.value for op in request.operations}
    assert ops[("Update", "environment")] == "outdoor"


def test_recommend_without_pending_clarification_still_resets() -> None:
    request = transform(
        _recommend(search_center="경복궁"),
        _context(pending_clarification=None),
        "경복궁 근처",
    )

    assert request.reset_scope == "soft"


def test_explicit_restart_overrides_pending_clarification() -> None:
    """되묻기 중이라도 명시적 재시작 표현은 새 요청으로 본다."""
    request = transform(
        _recommend(search_center="경복궁"),
        _context(pending_clarification="location_required"),
        "처음부터 다시 추천해줘",
    )

    assert request.reset_scope == "soft"


def _modify_exclude_tags(final: list[str], current: list[str]) -> list[tuple]:
    """exclude_tags 최종 목록을 넘겼을 때 만들어지는 operations를 (op, field, value)로."""

    request = transform(
        LLMOutput(
            intent=Intent.MODIFY,
            status=OutputStatus.COMPLETE,
            modify=ModifyPayload(
                modify_type=ModifyType.CHANGE_CONDITION,
                changed_fields=["exclude_tags"],
                condition_changes=UserConditions(exclude_tags=final),
            ),
        ),
        _context(user_conditions=StateUserConditions(exclude_tags=current)),
        "박물관도 포함해줘",
    )
    return [
        (op.op, op.field, op.value if op.has_value else None)
        for op in request.operations
    ]


def test_exclude_tags_partial_removal_becomes_remove_operation() -> None:
    """"박물관도 포함해줘" — Update로 보내면 B가 드롭하므로 Remove 차분을 만든다."""

    assert _modify_exclude_tags(["카페"], ["박물관", "카페"]) == [
        ("Remove", "exclude_tags", ["박물관"])
    ]


def test_exclude_tags_addition_becomes_add_operation() -> None:
    assert _modify_exclude_tags(["박물관", "카페"], ["박물관"]) == [
        ("Add", "exclude_tags", ["카페"])
    ]


def test_exclude_tags_swap_produces_remove_and_add() -> None:
    assert _modify_exclude_tags(["카페"], ["박물관"]) == [
        ("Remove", "exclude_tags", ["박물관"]),
        ("Add", "exclude_tags", ["카페"]),
    ]


def test_exclude_tags_unchanged_produces_no_operation() -> None:
    """값이 그대로면 연산을 만들지 않는다 — 불필요한 조건 변경 기록을 남기지 않는다."""

    assert _modify_exclude_tags(["박물관"], ["박물관"]) == []


def test_exclude_tags_cleared_still_uses_valueless_remove() -> None:
    """전체 해제는 기존 동작(값 없는 Remove)을 그대로 유지한다."""

    assert _modify_exclude_tags([], ["박물관", "카페"]) == [
        ("Remove", "exclude_tags", None)
    ]
