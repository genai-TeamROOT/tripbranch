"""state_transform.transform()의 LLMOutput → StateApplyRequest 변환 회귀 테스트.

docs/design/test-cases.md의 TC-07~09와 conditions-schema.md §5 예시5(place_tags 정리)를
재현한다.
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
from app.state.schema import UserConditions as StateUserConditions
from app.state.service import SessionContextResponse


def _context(
    *,
    session_id: str = "sess_1",
    shown_place_ids: list[str] | None = None,
    user_conditions: StateUserConditions | None = None,
) -> SessionContextResponse:
    return SessionContextResponse(
        session_id=session_id,
        session_exists=True,
        has_recommendation=bool(shown_place_ids),
        recommended_count=len(shown_place_ids or []),
        shown_place_ids=shown_place_ids or [],
        user_conditions=user_conditions or StateUserConditions(),
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


def test_recommend_skips_null_and_empty_fields() -> None:
    llm_output = LLMOutput(
        intent=Intent.RECOMMEND,
        status=OutputStatus.COMPLETE,
        recommend=RecommendPayload(conditions=UserConditions()),
    )

    request = transform(llm_output, _context(), "추천해줘")

    assert request.operations == []
    assert request.reset_scope == "soft"


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


def test_tc08_change_condition_budget_update_and_reason_other() -> None:
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
    assert all(r.reason_code == "other" for r in request.rejected_places)
    assert request.reset_scope is None


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
