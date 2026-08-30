"""Gemini 구조화 출력 호출에 쓰는 system instruction 모음.

역할: intent-definition.md / conditions-schema.md / int-01~05 문서의 판별 규칙과 추출
규칙을 LLM system instruction 문자열로 옮긴다. 호출/재시도/에러 처리 같은 코드는
app/providers/gemini.py에 두고, 이 모듈은 프롬프트 텍스트만 담아 gemini.py가
비대해지지 않게 한다.
호출 시점: RealGeminiProvider의 각 메서드가 build_* 함수로 동적 컨텍스트(이전 추천
이력 여부, 현재 조건 등)를 채운 system instruction을 만들 때 사용한다.
"""

from __future__ import annotations

from datetime import date

from app.prompts.loader import active_variant, load_text, render_text
from app.schedule.associations import CoVisitedHint
from app.schedule.schemas import (
    SchedulePartialFillRequest,
    SchedulePlanningRequest,
    target_item_range,
)
from app.schemas import (
    CompareCriteria,
    GeneralTopic,
    Intent,
    RecommendationItem,
    UserConditions,
)

# B의 LLMOps Trace(record_trace(prompt_version=...))와 StateApplyRequest.prompt_version에
# 넘길 값 — backend/docs/package-b/llmops-trace-contract-v1.md §7 Q2. B는 이 값의 의미를
# 해석하지 않고 문자열로만 저장한다(B-01 경계 원칙). app/domain/scoring.py의
# SCORING_VERSION과 동일한 semver 패턴. record_trace(step="llm_interpret", ...)는 턴당
# 한 번만 호출되고(agent_runtime.py) 이 모듈의 6개 build_*_instruction() 함수 중 어느 게
# 쓰였는지와 무관하게 단일 값으로 취급한다 — 함수별 개별 버전은 만들지 않는다. 판별·추출
# 규칙에 영향을 주는 변경(6개 함수 중 하나라도) 시 버전을 올린다 — 사소한 문구·주석
# 변경은 올리지 않는다.
_BASE_PROMPT_VERSION = "agent-interpret-prompts-1.0.24"
_ACTIVE_PROMPT_VARIANT = active_variant()
PROMPT_VERSION = (
    _BASE_PROMPT_VERSION
    if _ACTIVE_PROMPT_VARIANT == "current"
    else f"{_BASE_PROMPT_VERSION}+{_ACTIVE_PROMPT_VARIANT}"
)

CHATBOT_NAME = "트리비"


def build_intent_classification_instruction(
    *,
    has_previous_recommendation: bool,
    shown_place_count: int,
    pending_clarification: str | None = None,
    last_intent: str | None = None,
    shown_place_names: list[str] | None = None,
    conversation_place_name: str | None = None,
) -> str:
    """intent-definition.md §5(판별 우선순위·맥락 의존 판별·경계 사례) 기반 system instruction.

    shown_place_names는 SCHEDULE-09 후속(이름 지목)에서 추가됐다 — "두가헌
    레스토랑은 빼줘"처럼 순번 없이 노출된 항목 이름만 언급해도 MODIFY로 판단할
    근거를 준다. 없으면(이름 미저장 과거 세션 등) 이 블록은 생략된다.
    """

    schedule_clarification_pending = (
        last_intent == "SCHEDULE" and pending_clarification is not None
    )
    location_clarification_pending = (
        last_intent in {"RECOMMEND", "MODIFY"}
        and pending_clarification in {"location_required", "location_ambiguous"}
    )
    clarification_status = (
        "예 (직전 SCHEDULE 요청의 되묻기)"
        if schedule_clarification_pending
        else "예 (직전 RECOMMEND/MODIFY 요청의 위치 되묻기)"
        if location_clarification_pending
        else "아니오"
    )
    shown_names_line = ""
    if shown_place_names and any(name for name in shown_place_names):
        joined = ", ".join(name for name in shown_place_names if name)
        shown_names_line = f"\n- 현재 노출된 항목 이름: {joined}"
    conversation_place_line = ""
    if conversation_place_name:
        conversation_place_line = (
            f"\n- 직전 INFO 상세 카드 장소: {conversation_place_name}\n"
            "  사용자가 이 장소를 '여기', '이곳', '거기', '이리로'처럼 가리키며 "
            "운영시간·주차·요금·위치·찾아가는 시간 등을 묻는다면 INFO다. "
            "이번 발화에 다른 장소명을 직접 말하면 그 명시 장소를 우선한다."
        )

    return render_text(
        "router/classify.md",
        intent_definitions=load_text("router/intent_definitions.md"),
        intent_priority=load_text("router/intent_priority.md"),
        context_rules=load_text("router/context_rules.md"),
        boundary_cases=load_text("router/boundary_cases.md"),
        # interaction_mode는 Intent와 직교하는 별개 축이라 판별 규칙도 따로
        # 둔다(대화층 2단계) — 인텐트 우선순위 캐스케이드에 섞으면 GENERAL이
        # 다시 만능 라벨이 된다.
        interaction_mode=load_text("router/interaction_mode.md"),
        # OUT_OF_SCOPE 판정 자체는 분류기가 하지만, 규칙 문구의 소유는
        # out_of_scope/에 둔다 — 그래야 해당 인텐트 담당자도 자기 폴더만 열고
        # 수정·이력 관리를 할 수 있다.
        out_of_scope_rules=load_text("out_of_scope/classify.md"),
        has_previous_recommendation="있음" if has_previous_recommendation else "없음",
        shown_place_count=shown_place_count,
        clarification_status=clarification_status,
        shown_names_line=shown_names_line,
        conversation_place_line=conversation_place_line,
    )


def build_recommend_extraction_instruction() -> str:
    """int-01-recommend.md §5~9,12(위치 처리, place_types/tags, weather_intent) 기반."""

    return render_text(
        "recommend/extract.md",
        location_rules=load_text("recommend/location_rules.md"),
        place_tag_rules=load_text("recommend/place_tag_rules.md"),
        transport_rules=load_text("_shared/rules/transport.md"),
        weather_intent_rules=load_text("_shared/rules/weather_intent.md"),
        concentration_rules=load_text("_shared/rules/concentration_intent.md"),
        environment_rules=load_text("_shared/rules/environment.md"),
        budget_rule=load_text("_shared/rules/budget.md"),
    )


def _shown_place_list_block(shown_place_names: list[str] | None) -> str:
    """rank 순 이름 목록을 "1. 이름" 형태의 프롬프트 블록으로 만든다.

    이름이 하나도 없으면(과거 세션이라 저장이 안 됐거나 호출부가 안 넘김) 빈
    문자열을 돌려준다 — 목록 없이 이름 매칭을 시키면 모델이 근거 없이 순번을
    지어낸다. MODIFY와 COMPARE가 같은 형식을 쓰도록 한 곳에 둔다.
    """
    if not shown_place_names or not any(name for name in shown_place_names):
        return ""
    numbered = "\n".join(
        f"{index}. {name}" for index, name in enumerate(shown_place_names, start=1) if name
    )
    return (
        "\n"
        + render_text("_shared/rules/shown_place_list.md", shown_place_names=numbered)
        + "\n"
    )


def build_modify_extraction_instruction(
    current_conditions: UserConditions,
    *,
    pending_clarification: str | None = None,
    shown_place_count: int = 0,
    shown_place_names: list[str] | None = None,
) -> str:
    """int-03-modify.md §6,7,9,12(REJECT_ALL/CHANGE_CONDITION, 병합, "더 ~한 곳") 기반.

    shown_place_count는 SCHEDULE-09(부분 수정)에서 추가됐다. REJECT_SPECIFIC의
    target_indices가 실제 노출 범위를 벗어나는지 판별하는 데 쓰인다 —
    build_compare_extraction_instruction의 shown_place_count와 같은 역할이다.
    shown_place_names는 SCHEDULE-09 후속(이름 지목)에서 추가됐다 — rank 순
    이름 목록을 "1. 이름\\n2. 이름..." 형태로 프롬프트에 포함해 "두가헌
    레스토랑은 빼줘"처럼 이름으로 지목한 경우도 target_indices로 변환하게
    한다. 이름이 없거나(과거 세션) 전달되지 않으면 이 블록은 생략된다 —
    Gemini가 목록 없이 이름 매칭을 시도해 엉뚱한 순번을 만들어내는 것을
    막는다.
    """

    return render_text(
        "modify/extract.md",
        current_json=current_conditions.model_dump_json(indent=2),
        location_clarification_answer=(
            "예"
            if pending_clarification in {"location_required", "location_ambiguous"}
            else "아니오"
        ),
        shown_list_block=_shown_place_list_block(shown_place_names),
        type_rules=load_text("modify/type_rules.md"),
        target_rules=load_text("modify/target_rules.md"),
        shown_place_count=shown_place_count,
        relative_expression_rules=load_text("modify/relative_expression_rules.md"),
        field_merge_rules=load_text("modify/field_merge_rules.md"),
        transport_rules=load_text("_shared/rules/transport.md"),
        weather_intent_rules=load_text("_shared/rules/weather_intent.md"),
        concentration_rules=load_text("_shared/rules/concentration_intent.md"),
        environment_rules=load_text("_shared/rules/environment.md"),
        budget_rule=load_text("_shared/rules/budget.md"),
    )


def _build_visit_time_rules(reference_date: date) -> str:
    """concentration-conditions.md §3.2. reference_date는 오늘(KST)."""

    return render_text("info/visit_time_rules.md", reference_date=reference_date.isoformat())


def build_info_extraction_instruction(
    *,
    has_previous_recommendation: bool,
    reference_date: date,
    conversation_place_name: str | None = None,
) -> str:
    """int-02-info.md §4~7(InfoQuery, question_type, place_context) 기반."""

    return render_text(
        "info/extract.md",
        question_type_rules=load_text("info/question_type_rules.md"),
        place_context_rules=load_text("info/place_context_rules.md"),
        visit_time_rules=_build_visit_time_rules(reference_date),
        has_previous_recommendation="있음" if has_previous_recommendation else "없음",
        conversation_place_name=conversation_place_name or "없음",
    )


def build_compare_extraction_instruction(
    *,
    shown_place_count: int,
    shown_place_names: list[str] | None = None,
) -> str:
    """int-04-compare.md §5~7(targets, criteria) 기반.

    shown_place_names는 이름 지목("백인제가옥이랑 가회민화박물관 비교해줘")을
    순번으로 옮기기 위해 필요하다. 개수만 주던 때는 모델이 이름과 순번의 대응을
    알 방법이 없어 임의로 "all"이나 [1, 2]를 만들어냈고, 그래서 사용자가 지목한
    적 없는 장소가 비교 대상에 섞였다. MODIFY의 target_indices가 같은 이유로
    이미 이 목록을 받고 있다(SCHEDULE-09 후속).
    """

    return render_text(
        "compare/extract.md",
        shown_list_block=_shown_place_list_block(shown_place_names),
        target_rules=load_text("compare/target_rules.md"),
        criteria_rules=load_text("compare/criteria_rules.md"),
        shown_place_count=shown_place_count,
    )


def build_general_extraction_instruction() -> str:
    """int-05-general.md §5~6(GeneralRequest, topic) 기반."""

    return render_text("general/extract.md", topic_rules=load_text("general/topic_rules.md"))


def build_general_answer_instruction(topic: GeneralTopic) -> str:
    """GENERAL 발화에 실제로 답하는 system instruction(docs/design/agent-response-
    generation.md §3/§6 — 6개 Intent 중 실제 LLM 자유생성이 필요한 유일한 지점).

    build_general_extraction_instruction()과 별개 호출이다 — 저건 topic만 분류하고,
    이건 그 topic이 확정된 뒤 실제 답변 문장을 만든다.
    """

    return render_text(
        "general/answer_instruction.md",
        chatbot_name=CHATBOT_NAME,
        persona=load_text("_shared/persona/trivi.md"),
        topic=topic.value,
    )


def build_info_answer_instruction(question_type: str) -> str:
    """검증된 INFO fields만 사용자용 안내문으로 바꾸는 system instruction."""

    return render_text(
        "info/answer_instruction.md",
        chatbot_name=CHATBOT_NAME,
        persona=load_text("_shared/persona/trivi.md"),
        question_type=question_type,
    )


def build_follow_up_suggestion_instruction(
    *, max_suggestions: int, max_label_length: int
) -> str:
    """방금 끝난 턴을 보고 다음 발화 후보를 만드는 system instruction.

    다른 build_*와 달리 특정 Intent에 매이지 않는다 — 어떤 Intent로 끝난 턴이든 그
    뒤에 한 번 돈다. 대신 `follow_up/capability_rules.md`가 서비스가 실제로 처리할 수
    있는 요청 목록을 싣는다. 버튼을 누르면 그 문구가 그대로 사용자 발화로 전송되므로,
    모델이 없는 기능을 권하면 사용자는 곧바로 OUT_OF_SCOPE 답변을 받게 된다.

    개수·길이 상한을 지침에도 넣지만 이걸 지켰는지는 호출부
    (`services/runtime/follow_up_suggester.py`)가 코드로 다시 검사한다 — 여기 적은
    상한은 부탁이고, 그쪽 검사가 실제 계약이다.
    """

    return render_text(
        "follow_up/suggest_instruction.md",
        chatbot_name=CHATBOT_NAME,
        persona=load_text("_shared/persona/trivi.md"),
        capabilities=load_text("follow_up/capability_rules.md"),
        max_suggestions=str(max_suggestions),
        max_label_length=str(max_label_length),
    )


def build_recommendation_summary_instruction(intent: Intent) -> str:
    """RECOMMEND/MODIFY 결과를 감싸는 짧은 말풍선 생성 system instruction."""

    return render_text(
        "recommend/summary_instruction.md",
        chatbot_name=CHATBOT_NAME,
        persona=load_text("_shared/persona/trivi.md"),
        intent=intent.value,
    )


def build_compare_summary_instruction(criteria: CompareCriteria) -> str:
    """C의 검증된 COMPARE 결과를 사용자용 문장으로 바꾸는 system instruction."""

    return render_text(
        "compare/summary_instruction.md",
        chatbot_name=CHATBOT_NAME,
        persona=load_text("_shared/persona/trivi.md"),
        criteria=criteria.value,
    )


def _schedule_candidate_line(candidate: RecommendationItem) -> str:
    """일정 편성용 후보 1건을 프롬프트 한 줄로 직렬화한다.

    operating_hours_display를 포함해 LLM이 후보별 운영시간을 보고, 뒤 순서에
    배치하면 도착 예정 시각(estimated_arrival) 기준으로 이미 닫혀 있을 곳을
    스스로 피하도록 돕는다. 다만 이 프롬프트 힌트만으로는 LLM이 지시를 놓칠
    수 있어 완전한 보장이 아니다 — app.schedule.planner가 응답을 받은 뒤
    estimated_arrival과 운영시간을 다시 대조해 구조적으로 재검증한다
    (docs/design/int-07-schedule.md 9절, "폐점 스탑 감지" 항목 해소. 이
    한 줄짜리 프롬프트 힌트만으로 부족하다고 판단한 근거는 같은 문서 6.2.1절 —
    근거 데이터가 단일 시각 기준이라 프롬프트만으로는 뒷 순서 스탑의 정확성을
    보장할 수 없다).
    """
    hours = candidate.operating_hours_display or "확인불가"
    return (
        f"- {candidate.place_id} | {candidate.name} | {candidate.category} | "
        f"운영시간={hours} | score={candidate.score:.2f} | "
        f"{candidate.recommendation_reason}"
    )


def build_schedule_planning_instruction(time_available_min: int | None = None) -> str:
    """INT-07 SCHEDULE 일정 편성 system instruction.
    (docs/design/int-07-schedule.md 6.1~6.2절)

    format_schedule_planning_context()가 만드는 텍스트가 contents로 같이
    전달된다는 전제로 규칙만 담는다 — 다른 build_*_instruction()과 달리 원문
    사용자 발화가 아니라 구조화된 후보/조건/거리 데이터가 입력이기 때문이다.

    time_available_min으로 이번 요청에 맞는 목표 개수 범위를 계산해(target_item_range())
    프롬프트에 직접 반영한다(SCHEDULE-10). 이전에는 항상 "3~5개"로 고정 지시해서,
    활동 가능 시간이 짧은 요청(예: "2시간 코스 짜줘")에서 LLM이 체류시간을
    비현실적으로 줄이거나 개수 지시 자체를 못 맞춰 검증 실패로 이어지는 문제가
    있었다 — 요청마다 실제로 달성 가능한 개수를 알려주는 쪽으로 바꿨다.

    (2026-08-18 추가) target_item_range()가 계산한 상한(max_items)까지는 실제로
    채우도록 프롬프트가 명시적으로 유도한다. "6시간 코스 짜줘"처럼 활동 가능
    시간이 긴 요청에서 목표 개수 범위(예: 3~5개) 안에 들어오는데도 LLM이 훨씬
    적은 개수·짧은 체류시간만 채우고 일찍 끝내버리는 과소-채움(under-fill)이
    실사용 테스트에서 확인됐다(docs/design/int-07-schedule.md 9절). 기존
    duration_rule 문구는 "시간이 짧으면 줄이라"는 하한 방향 지시만 있었고, 시간이
    넉넉할 때 상한 방향으로 채우라는 지시가 없었던 게 원인이라, 아래 else 분기에
    상한 지시를 추가했다. target_item_range() 자체의 상한 계산이나
    ScheduleLLMPlan의 max_length=5 하드 캡은 건드리지 않았다 — 순수 프롬프트
    문구만 바꾼 변경이다.
    """

    min_items, max_items = target_item_range(time_available_min)
    count_phrase = f"{min_items}개" if min_items == max_items else f"{min_items}~{max_items}개"

    if time_available_min is None:
        duration_rule = (
            "조건에 활동 가능 시간(time_available, 분)이 없으면 3~4시간 내외로 "
            "구성하세요."
        )
    else:
        duration_rule = (
            f"활동 가능 시간이 {time_available_min}분이니 총 소요 시간이 그 안에 "
            f"최대한 가깝게 차도록 구성하세요 — 목표 개수({count_phrase}) 안에서도 "
            f"너무 일찍 끝내지 마세요. 시간이 넉넉하면 개수를 {max_items}개에 "
            "가깝게 채우고 장소별 체류시간도 넉넉히 잡아 실제로 그 시간을 다 "
            "쓰도록 하세요. 반대로 시간이 짧다면 무리하게 채우려 하지 말고 "
            "개수를 줄이세요."
        )

    return render_text(
        "schedule/plan.md",
        count_phrase=count_phrase,
        min_items=min_items,
        max_items=max_items,
        duration_rule=duration_rule,
    )


def _co_visited_line(hint: CoVisitedHint, name_by_place_id: dict[str, str]) -> str:
    from_name = name_by_place_id.get(hint.from_place_id, hint.from_place_id)
    to_name = name_by_place_id.get(hint.to_place_id, hint.to_place_id)
    return f"- {from_name}({hint.from_place_id}) ↔ {to_name}({hint.to_place_id}) | rank={hint.rank}"


def format_schedule_planning_context(request: SchedulePlanningRequest, start_time: str) -> str:
    """SchedulePlanningRequest를 LLM에 전달할 contents 텍스트로 직렬화한다.

    build_schedule_planning_instruction()이 규칙(system instruction)을 담당하고,
    이 함수가 실제 후보/조건/거리 데이터(contents)를 담당한다. start_time은
    호출부(app.schedule.planner)가 request.visit_datetime의 fallback까지
    반영해 미리 "HH:MM"으로 계산해 넘긴다.

    co_visited_hints(place_associations 기반, D-088)는 대부분의 요청에서
    비어 있다 — planner.py가 co_visited_fetcher를 받았을 때만 채운다. 비어
    있으면 "(없음)"으로 표시해, 이 섹션이 있는지 없는지가 아니라 항상 같은
    구조로 렌더링되게 한다(format_schedule_fill_context()의 pinned_lines
    fallback과 같은 패턴).
    """

    candidate_lines = "\n".join(
        _schedule_candidate_line(c) for c in request.candidates
    )
    distance_lines = "\n".join(
        f"- {a}-{b}: {distance_km:.2f}km"
        for (a, b), distance_km in request.pairwise_distances_km.items()
    )
    name_by_place_id = {c.place_id: c.name for c in request.candidates}
    co_visited_lines = "\n".join(
        _co_visited_line(hint, name_by_place_id) for hint in request.co_visited_hints
    ) or "(없음)"
    condition_lines = request.conditions.model_dump_json(exclude_none=True)

    return render_text(
        "schedule/plan_context.md",
        start_time=start_time,
        candidate_lines=candidate_lines,
        distance_lines=distance_lines,
        co_visited_lines=co_visited_lines,
        condition_lines=condition_lines,
    )


def build_schedule_fill_instruction() -> str:
    """SCHEDULE-09(부분 수정) 2단계 — 기존 일정 중 일부 자리만 새로 채우는
    system instruction. (SCHEDULE-부분수정-해결방향-설계안.md 3-3절)

    build_schedule_planning_instruction()과 달리 pinned_items를 결과에 다시
    담아 달라고 요청하지 않는다 — 유지 항목은 이미 확정돼 있으므로 LLM은
    비어있는 자리(target_orders)에 들어갈 항목만 새로 고르면 된다. echo를
    신뢰하지 않고 Python이 병합을 구조적으로 보장한다.
    """

    return load_text("schedule/fill.md")


def format_schedule_fill_context(request: SchedulePartialFillRequest, start_time: str) -> str:
    """SchedulePartialFillRequest를 LLM에 전달할 contents 텍스트로 직렬화한다.

    co_visited_hints(D-088/D-091)는 pinned_items + candidates 양쪽 place_id를
    다 조회 대상으로 삼으므로(app.schedule.planner._with_co_visited_hints),
    이름 매핑도 두 목록을 합쳐서 만든다 — 힌트 한 쪽이 이미 확정된 pinned
    항목을 가리킬 수 있어서다.
    """

    pinned_lines = "\n".join(
        f"- order={p.order} | {p.place_id} | {p.place_name} | "
        f"도착={p.estimated_arrival} | 체류={p.estimated_duration_min}분"
        for p in request.pinned_items
    ) or "(없음)"
    candidate_lines = "\n".join(
        _schedule_candidate_line(c) for c in request.candidates
    )
    distance_lines = "\n".join(
        f"- {a}-{b}: {distance_km:.2f}km"
        for (a, b), distance_km in request.pairwise_distances_km.items()
    )
    name_by_place_id = {p.place_id: p.place_name for p in request.pinned_items}
    name_by_place_id.update({c.place_id: c.name for c in request.candidates})
    co_visited_lines = "\n".join(
        _co_visited_line(hint, name_by_place_id) for hint in request.co_visited_hints
    ) or "(없음)"
    condition_lines = request.conditions.model_dump_json(exclude_none=True)

    return render_text(
        "schedule/fill_context.md",
        start_time=start_time,
        pinned_lines=pinned_lines,
        target_orders=request.target_orders,
        candidate_lines=candidate_lines,
        distance_lines=distance_lines,
        co_visited_lines=co_visited_lines,
        condition_lines=condition_lines,
    )


def format_validation_retry_note(error: Exception) -> str:
    """1차 구조화 출력이 검증에 실패했을 때 재시도 프롬프트에 덧붙이는 안내문."""

    return "\n\n" + render_text("_shared/rules/validation_retry.md", error=error)


__all__ = [
    "PROMPT_VERSION",
    "build_intent_classification_instruction",
    "build_recommend_extraction_instruction",
    "build_modify_extraction_instruction",
    "build_info_extraction_instruction",
    "build_compare_extraction_instruction",
    "build_general_extraction_instruction",
    "build_general_answer_instruction",
    "build_info_answer_instruction",
    "build_recommendation_summary_instruction",
    "build_follow_up_suggestion_instruction",
    "build_compare_summary_instruction",
    "build_schedule_planning_instruction",
    "format_schedule_planning_context",
    "build_schedule_fill_instruction",
    "format_schedule_fill_context",
    "format_validation_retry_note",
]
