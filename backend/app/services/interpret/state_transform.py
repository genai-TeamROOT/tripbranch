"""LLMOutput을 B(Agent State)의 StateApplyRequest로 변환한다.

역할: A(LLM 해석 결과)와 B(Agent State) 사이의 유일한 변환 지점. LLMOutput의 intent별
payload를 읽고 operations/rejected_places/reset_scope로 바꾸는 건 해석 행위이므로 A의
책임이다(llm-output-schema.md §9 확정 사항 #1). B는 LLMOutput 원본을 받지 않는다.
입력: LLMOutput, 변환 시점의 SessionContextResponse(get_session_context() 응답),
사용자 원문 발화(reset_scope 판정에 필요 — LLMOutput 자체엔 MODIFY 원문이 없다).
출력: app.state.service.StateApplyRequest(B의 apply()가 그대로 받는 요청 모델).
"""

from __future__ import annotations

from app.schemas import (
    Intent,
    LLMOutput,
    ModifyType,
    OutputStatus,
    PlaceTag,
    PlaceType,
    UserConditions,
)
from app.state.operations import Operation
from app.state.schema import UserConditions as StateUserConditions
from app.state.service import RejectedPlace, SessionContextResponse, StateApplyRequest

_SINGLE_FIELDS = (
    "current_location",
    "search_center",
    "weather",
    "weather_intent",
    "transport",
    "max_travel_time",
    "time_available",
    "environment",
    "companion",
    "budget",
)
_MULTI_FIELDS = ("place_types", "place_tags", "exclude_tags", "special_requirements")
_KNOWN_FIELDS = frozenset(_SINGLE_FIELDS) | frozenset(_MULTI_FIELDS)

# int-01-recommend.md §7 place_tag → place_type 매핑 (39개, conditions-schema.md §2 전문 기준).
_TAG_TO_TYPE: dict[PlaceTag, PlaceType] = {
    # attraction 하위
    PlaceTag.PARK: PlaceType.ATTRACTION,
    PlaceTag.PALACE: PlaceType.ATTRACTION,
    PlaceTag.MOUNTAIN: PlaceType.ATTRACTION,
    PlaceTag.BEACH: PlaceType.ATTRACTION,
    PlaceTag.LAKE: PlaceType.ATTRACTION,
    PlaceTag.VALLEY: PlaceType.ATTRACTION,
    PlaceTag.VIEWPOINT: PlaceType.ATTRACTION,
    PlaceTag.THEME_PARK: PlaceType.ATTRACTION,
    PlaceTag.ZOO: PlaceType.ATTRACTION,
    PlaceTag.ARBORETUM: PlaceType.ATTRACTION,
    PlaceTag.TEMPLE: PlaceType.ATTRACTION,
    PlaceTag.FORTRESS: PlaceType.ATTRACTION,
    PlaceTag.VILLAGE: PlaceType.ATTRACTION,
    PlaceTag.TRAIL: PlaceType.ATTRACTION,
    PlaceTag.TRADITIONAL_EXPERIENCE: PlaceType.ATTRACTION,
    PlaceTag.CRAFT_EXPERIENCE: PlaceType.ATTRACTION,
    PlaceTag.WELLNESS: PlaceType.ATTRACTION,
    # cultural_facility 하위
    PlaceTag.MUSEUM: PlaceType.CULTURAL_FACILITY,
    PlaceTag.ART_GALLERY: PlaceType.CULTURAL_FACILITY,
    PlaceTag.LIBRARY: PlaceType.CULTURAL_FACILITY,
    PlaceTag.PERFORMANCE_HALL: PlaceType.CULTURAL_FACILITY,
    PlaceTag.SCIENCE_MUSEUM: PlaceType.CULTURAL_FACILITY,
    PlaceTag.EXHIBITION_HALL: PlaceType.CULTURAL_FACILITY,
    # festival 하위
    PlaceTag.FESTIVAL: PlaceType.FESTIVAL,
    PlaceTag.EXHIBITION: PlaceType.FESTIVAL,
    PlaceTag.PERFORMANCE: PlaceType.FESTIVAL,
    PlaceTag.CONCERT: PlaceType.FESTIVAL,
    # shopping 하위
    PlaceTag.MARKET: PlaceType.SHOPPING,
    PlaceTag.SHOPPING_MALL: PlaceType.SHOPPING,
    PlaceTag.DUTY_FREE: PlaceType.SHOPPING,
    PlaceTag.DEPARTMENT_STORE: PlaceType.SHOPPING,
    # restaurant 하위
    PlaceTag.KOREAN_FOOD: PlaceType.RESTAURANT,
    PlaceTag.JAPANESE_FOOD: PlaceType.RESTAURANT,
    PlaceTag.CHINESE_FOOD: PlaceType.RESTAURANT,
    PlaceTag.WESTERN_FOOD: PlaceType.RESTAURANT,
    PlaceTag.CAFE: PlaceType.RESTAURANT,
    PlaceTag.TEA_HOUSE: PlaceType.RESTAURANT,
    PlaceTag.BAR: PlaceType.RESTAURANT,
    PlaceTag.SNACK: PlaceType.RESTAURANT,
}

# int-03-modify.md §8 기준. 순서가 판정 우선순위다(먼저 매칭되는 문구가 채택됨).
_RESET_SCOPE_PHRASES: tuple[tuple[str, str], ...] = (
    ("처음부터 다시", "history"),
    ("조건 다시 정할게", "soft"),
    ("조건 다시 정하고 싶어", "soft"),
    ("새로 시작", "full"),
)


def transform(
    llm_output: LLMOutput,
    session_context: SessionContextResponse,
    user_input: str,
) -> StateApplyRequest:
    """LLMOutput + 현재 세션 컨텍스트를 B가 받는 StateApplyRequest로 변환한다."""

    confirmed = llm_output.status is OutputStatus.COMPLETE
    operations: list[Operation] = []
    rejected_places: list[RejectedPlace] = []
    reset_scope: str | None = None

    if llm_output.intent is Intent.RECOMMEND and llm_output.recommend is not None:
        # 새 RECOMMEND는 조건을 재생성한다(conditions-schema.md §6) — soft는 조건만
        # 초기화하고 추천/거절 이력은 유지해, 이후 MODIFY("그거 말고")가 계속 동작한다.
        reset_scope = "soft"
        operations = _full_replace_operations(llm_output.recommend.conditions)

    elif llm_output.intent is Intent.MODIFY and llm_output.modify is not None:
        modify = llm_output.modify
        if modify.modify_type is ModifyType.REJECT_ALL:
            rejected_places = _rejected_from_shown(session_context, "not_interested")
        elif modify.condition_changes is not None:
            operations = _changed_field_operations(
                modify.condition_changes, modify.changed_fields
            )
            operations.extend(
                _place_tag_cleanup_operations(
                    modify.condition_changes, modify.changed_fields, session_context
                )
            )
            # CHANGE_CONDITION은 사용자가 싫어서가 아니라 조건이 바뀌어서 제외되는
            # 것이므로 REJECT_ALL의 not_interested와 reason_code를 구분한다.
            rejected_places = _rejected_from_shown(session_context, "other")
        reset_scope = _detect_reset_scope(user_input, modify.changed_fields)

    # INFO/COMPARE/GENERAL/OUT_OF_SCOPE: operations=[], rejected_places=[], reset_scope=None.

    return StateApplyRequest(
        session_id=session_context.session_id,
        intent=llm_output.intent.value,
        confirmed=confirmed,
        reset_scope=reset_scope,
        operations=operations,
        rejected_places=rejected_places,
        prompt_version=None,  # TODO: 프롬프트 버전 값이 확정되면 채운다.
    )


def to_user_conditions(state_conditions: StateUserConditions) -> UserConditions:
    """B↔A 변환의 유일한 지점: app.state.schema.UserConditions(B, 순수 문자열)를
    app.schemas.UserConditions(A, enum 타입)로 변환한다.

    A↔C 변환(app.services.runtime.context_transform.to_agent_context_request())과
    혼동하지 않는다 — 이 함수는 B→A 한 구간만 담당한다. D 계약이 확정되면 A↔D 변환
    함수가 또 하나 늘어날 텐데, 그때도 이 세 변환 지점을 서로 섞지 않는다.

    MODIFY 조건 추출 시(build_interpretation의 MODIFY 분기) 현재 조건을 다시 LLM에
    넘기려면 A의 enum 타입 UserConditions가 필요하다. 두 모델은 필드 이름·개수가
    완전히 동일하므로 dict 왕복으로 충분하다 — StrEnum이 문자열 값을 그대로 받아들인다.
    """

    return UserConditions.model_validate(state_conditions.model_dump())


def _serialize(value: object) -> object:
    """StrEnum(PlaceTag 등)을 순수 str/list[str]로 변환한다.

    StrEnum은 str 서브클래스라 B의 matches_type()는 이미 통과하지만, 로그·JSON 직렬화가
    항상 순수 문자열이 되도록 방어적으로 변환한다.
    """
    if isinstance(value, list):
        return [str(item) for item in value]
    return str(value)


def _full_replace_operations(conditions: UserConditions) -> list[Operation]:
    """RECOMMEND: conditions의 non-null/non-empty 필드 전부를 Update로 변환한다."""

    operations: list[Operation] = []
    for field in _SINGLE_FIELDS:
        value = getattr(conditions, field)
        if value is not None:
            operations.append(Operation(op="Update", field=field, value=_serialize(value)))
    for field in _MULTI_FIELDS:
        value = getattr(conditions, field)
        if value:
            operations.append(Operation(op="Update", field=field, value=_serialize(value)))
    return operations


def _changed_field_operations(
    condition_changes: UserConditions, changed_fields: list[str]
) -> list[Operation]:
    """MODIFY/CHANGE_CONDITION: changed_fields에 있는 필드만 Operation으로 만든다.

    changed_fields에 없는 필드는 (condition_changes에 어떤 값이 있든) Keep이므로 건드리지
    않는다 — operations 배열에 없으면 자동 Keep(tests/state/test_service.py로 확인됨).
    """

    operations: list[Operation] = []
    for field in changed_fields:
        if field not in _KNOWN_FIELDS:
            continue  # LLM 환각 등으로 알 수 없는 필드명이 오면 무시한다.
        value = getattr(condition_changes, field)
        if value is None or value == []:
            # Update에 value=None은 B에서 null_value 오류로 거부되므로 Remove를 쓴다.
            operations.append(Operation(op="Remove", field=field))
        else:
            operations.append(Operation(op="Update", field=field, value=_serialize(value)))
    return operations


def _tag_place_type(tag_value: str) -> PlaceType | None:
    try:
        return _TAG_TO_TYPE.get(PlaceTag(tag_value))
    except ValueError:
        return None  # 알 수 없는 태그는 정리 대상에서 제외(보수적으로 그대로 둔다).


def _place_tag_cleanup_operations(
    condition_changes: UserConditions,
    changed_fields: list[str],
    session_context: SessionContextResponse,
) -> list[Operation]:
    """place_types 교체 시 소속 안 되는 place_tags에 Remove를 자동 생성한다.

    (conditions-schema.md §5 예시5) LLM이 이미 place_tags 최종값을 changed_fields에
    넘겼으면(= place_tags도 변경 필드로 포함) 여기서 다시 계산하지 않는다.
    """

    if "place_types" not in changed_fields or "place_tags" in changed_fields:
        return []

    new_types = set(condition_changes.place_types)
    current_tags = session_context.user_conditions.place_tags
    orphaned = [
        tag
        for tag in current_tags
        if (tag_type := _tag_place_type(tag)) is not None and tag_type not in new_types
    ]
    if not orphaned:
        return []
    return [Operation(op="Remove", field="place_tags", value=orphaned)]


def _rejected_from_shown(
    session_context: SessionContextResponse, reason_code: str
) -> list[RejectedPlace]:
    return [
        RejectedPlace(place_id=place_id, reason_code=reason_code)
        for place_id in session_context.shown_place_ids
    ]


def _detect_reset_scope(user_input: str, changed_fields: list[str]) -> str | None:
    """MODIFY에서만 호출된다. reset_scope는 B가 자동 판단하지 않으므로 A가 명시한다."""

    for phrase, scope in _RESET_SCOPE_PHRASES:
        if phrase in user_input:
            return scope
    if "search_center" in changed_fields:
        return "history"
    return None


__all__ = ["transform", "to_user_conditions"]
