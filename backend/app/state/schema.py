"""Package B - Agent State 데이터 모델.

계약 문서: docs/package-b/agent-state-contract-v1.md (1절, 3절)
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    """타임존이 포함된 현재 시각."""
    return datetime.now(KST)


# ---------------------------------------------------------------- 조건

class UserConditions(BaseModel):
    """사용자 발화에서 추출된 조건 15개. (계약 1.2절)

    B는 각 필드의 허용값을 검증하지 않는다. 허용값 정의는 Package A의 책임이다.
    """

    current_location: str | None = None
    search_center: str | None = None
    place_types: list[str] = Field(default_factory=list)
    place_tags: list[str] = Field(default_factory=list)
    weather: str | None = None
    weather_intent: str | None = None
    concentration_intent: str | None = None
    transport: str | None = None
    max_travel_time: int | None = None   # 분
    time_available: int | None = None    # 분
    environment: str | None = None
    companion: str | None = None
    budget: str | None = None
    exclude_tags: list[str] = Field(default_factory=list)
    special_requirements: list[str] = Field(default_factory=list)
    taste_query: str | None = None


class ApiContext(BaseModel):
    """외부 API로 확보한 데이터. (계약 1.4절)

    operations 대상이 아니며 별도 경로로 갱신한다.
    condition_version 증가 판정에서 제외한다.
    """

    gps_location: str | None = None
    api_weather: str | None = None
    gps_location_updated_at: datetime | None = None
    api_weather_updated_at: datetime | None = None
    # PR #188: 위치 재확인 UX(30분 경과 시 "N분 전 위치로 계속"/"현재 위치 다시
    # 가져오기") 서버 상태 반영. gps_location_updated_at은 GPS 데이터의 기술적
    # TTL(1시간) 의미를 유지하고, 이 필드는 사용자가 실제로 재확인(현재 위치
    # 다시 가져오기)한 시각만 담아 혼용하지 않는다 — "N분 전 위치로 계속"을
    # 선택하면 이 값은 갱신되지 않는다. A가 이 값과 now를 비교해 30분 경과
    # 여부를 서버 상태 기준으로 판단한다. 기존 세션은 null(최초 재확인 대상).
    gps_location_confirmed_at: datetime | None = None


# ---------------------------------------------------------------- 상태

class AgentState(BaseModel):
    """세션 단위 현재 상태. (계약 1.6절)"""

    session_id: str
    # 검증된 신원(Principal.user_id)이 연결되면 채워진다. 비어 있으면 채우고,
    # 값이 있으면 절대 덮어쓰지 않는다(D-063 결정 3) — session.py의 연결
    # 로직이 이 규칙을 지킨다. FK는 걸지 않는다(D-063 결정 4).
    user_id: str | None = None
    user_conditions: UserConditions = Field(default_factory=UserConditions)
    api_context: ApiContext = Field(default_factory=ApiContext)
    condition_version: int = 0
    last_run_id: str | None = None
    last_intent: str | None = None
    # 직전 턴이 되묻기로 끝났을 때 그 사유 코드(예: "location_required").
    # B는 판단하지 않고 A가 준 값을 보관만 한다 — 되묻기 판정은 LLM과 C가 하고,
    # 소비(부분 갱신 여부 결정)는 A의 state_transform이 한다.
    pending_clarification: str | None = None
    # "운영 중이 아닌 곳도 볼게요"를 한 번 선택하면 이 시각까지는 매 턴 다시
    # 묻지 않고 폐점 후보도 계속 포함한다(실사용 피드백, 2026-08-13 — 매 턴
    # 버튼을 다시 눌러야 하는 게 불편하다는 지적).
    ignore_operating_hours_until: datetime | None = None
    status: Literal["active", "expired"] = "active"
    created_at: datetime = Field(default_factory=now_kst)
    updated_at: datetime = Field(default_factory=now_kst)
    last_active_at: datetime = Field(default_factory=now_kst)


# ---------------------------------------------------------------- 이력

class RecommendedItem(BaseModel):
    """노출된 장소 1건. (계약 3.2절)

    estimated_arrival~reason 4개 필드는 SCHEDULE 전용 선택 필드다(SCHEDULE-06).
    distance_km~environment_type 3개 필드는 COMPARE 전용 선택 필드다
    (COMPARE 데이터 출처 A안, 2026-08-11). name은 SCHEDULE-09 2단계 전용
    선택 필드다(2026-08-11, D-060 — 아래 설명 참고). 셋 다 RECOMMEND-only
    흐름에서는 관련 없는 필드가 None으로 남는다.

    "B는 place_id만 저장하고 장소 상세 정보를 보관하지 않는다"는 원칙
    (history.py 참고)의 세 가지 예외다 — 일반 장소 상세(주소·좌표 등)는
    여전히 C의 책임이고 B가 저장하지 않는다. 여기 저장하는 값은 그 자체가
    "추천 시점에 계산된 Feature 스냅샷"이라, 시간이 지나 실제 값과 달라져도
    문제가 되지 않는다 — 오히려 COMPARE는 최신값이 아니라 이 스냅샷을 써야
    한다(int-04-compare.md §13). "과거 정보가 현재 정보로 오인되는" 상황을
    막으려는 원 원칙과 배치되지 않는 이유는, 이 값을 "현재 상태"로 다시
    쓰는 소비자가 없고 오직 "그때 보여준 비교 데이터"로만 쓰이기 때문이다.

    name(장소 이름)은 원래 이 예외에 넣지 않고 SCHEDULE-09 2단계에서 매 턴
    C의 새 응답에서 다시 매칭해 채우도록 설계했다. 그런데 실사용 테스트에서
    "경복궁" 같은 지명 검색이 호출마다 조금씩 다른 좌표로 resolve돼(Naver
    local search fallback) 이번 턴 주변 후보 목록이 매번 완전히 달라지는
    사례가 확인됐다 — 그러면 이전 턴에 고른 place_id가 이번 턴 후보에
    전혀 안 잡혀 이름을 못 채우고, pinned 유지가 통째로 실패해 REJECT_ALL처럼
    전체 재편성으로 조용히 폴백된다(2026-08-11 실사용 재현). name도 여기
    저장해두면 이 재검색에 의존하지 않아 안정적이다.

    rank가 이미 방문 순서(ScheduleItem.order)를 담으므로 별도 order
    필드는 두지 않는다.
    """

    place_id: str
    run_id: str
    rank: int
    shown_at: datetime = Field(default_factory=now_kst)
    name: str | None = None
    estimated_arrival: str | None = None
    estimated_duration_min: int | None = None
    travel_to_next_min: int | None = None
    reason: str | None = None
    distance_km: float | None = None
    remaining_minutes: int | None = None
    environment_type: str | None = None


class RecommendedItemInput(BaseModel):
    """history.record_recommended() 호출 시 넘기는 입력 1건.

    place_id/rank는 필수, 나머지는 SCHEDULE 전용(SCHEDULE-06),
    COMPARE 전용(2026-08-11) 또는 SCHEDULE-09 2단계 전용(2026-08-11,
    name) 선택 필드다.
    """

    place_id: str
    rank: int
    name: str | None = None
    estimated_arrival: str | None = None
    estimated_duration_min: int | None = None
    travel_to_next_min: int | None = None
    reason: str | None = None
    distance_km: float | None = None
    remaining_minutes: int | None = None
    environment_type: str | None = None


class RejectedItem(BaseModel):
    """거절된 장소 1건. (계약 3.2절)

    reason_code는 Package A가 해석한 값을 그대로 저장하며 검증하지 않는다.
    """

    place_id: str
    run_id: str
    reason_code: str | None = None
    rejected_at: datetime = Field(default_factory=now_kst)


class ClosedExclusionItem(BaseModel):
    """D의 하드 필터(_is_closed)가 폐점이라 걸러낸 후보 1건. (TP-82)

    recommended/rejected와 달리 "노출됐다"도 "사용자가 거절했다"도 아니다 —
    D 응답에 아예 담기지 못해 노출 이력 경로를 탈 수 없는 후보를 별도로
    추적하기 위한 항목이다. 운영시간은 시각에 따라 바뀌므로(닫혀 있던
    곳이 다음 날 다시 열림) recommended/rejected처럼 영구 보관하지 않고,
    clear_recommended()에서 함께 비운다(history.py 참고).
    """

    place_id: str
    run_id: str
    excluded_at: datetime = Field(default_factory=now_kst)


class RecommendationHistory(BaseModel):
    """세션 단위 추천·거절 이력. append-only. (계약 3.2절)"""

    session_id: str
    # AgentState.user_id와 동일한 규칙(TP-101 3단계, D-063): 비어 있으면
    # 채우고, 값이 있으면 덮어쓰지 않는다. FK는 걸지 않는다.
    user_id: str | None = None
    recommended: list[RecommendedItem] = Field(default_factory=list)
    rejected: list[RejectedItem] = Field(default_factory=list)
    # TP-82: D의 하드 필터가 폐점이라 걸러낸 후보 id. recommended/rejected와
    # 분리된 별도 리스트다 — "노출했다"로 잘못 취급되면 COMPARE의 "첫 번째"가
    # 실제로 안 보여준 장소를 가리키게 된다(댓글/카드 참고).
    closed_excluded: list[ClosedExclusionItem] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=now_kst)


# ---------------------------------------------------------------- 기록

class ConditionChangeLog(BaseModel):
    """조건 변경 기록 1건. append-only. (계약 2.8절, 5.5절)

    사용자 원문 발화와 LLM 원문 응답은 기록하지 않는다.
    """

    session_id: str
    run_id: str
    seq: int
    op: str                       # Add / Update / Remove / Reset
    field: str | None = None      # Reset인 경우 None
    before_value: Any = None
    after_value: Any = None
    reset_scope: str | None = None
    applied_at: datetime = Field(default_factory=now_kst)


class TraceRecord(BaseModel):
    """실행 단계 1건. append-only. (docs/package-b/llmops-trace-contract-v1.md 2절)

    step/prompt_version/scoring_version/variant_id/error_type은 호출자(A/C/D)가
    해석한 값을 그대로 저장하며 검증하지 않는다 — B는 값의 의미를 판단하지 않는다.
    """

    session_id: str
    run_id: str
    trace_id: str
    step: str
    prompt_version: str | None = None
    scoring_version: str | None = None
    variant_id: str | None = None
    latency_ms: int | None = None
    token_usage: int | None = None
    error_type: str | None = None
    recorded_at: datetime = Field(default_factory=now_kst)


class FeedbackRecord(BaseModel):
    """응답 1건에 대한 사용자 반응. append-only. (roadmap.md 14번)

    trace_id(run 내부 한 단계)가 아니라 run_id(그 턴의 최종 응답) 단위로
    붙는다 — 사용자는 "이 답변"에 좋아요/싫어요를 누르는 것이지, 그 답변을
    만든 개별 단계(LLM 호출/Tool 호출/Scoring)에 반응하는 게 아니다.
    rating은 화면 버튼이 만드는 고정된 두 값이라(TraceRecord의 step 등과
    달리 호출자가 자유롭게 정하는 값이 아니다) Literal로 검증한다.

    user_input/assistant_message는 2026-08-21 추가된 선택 필드다. B는 원칙적으로
    대화 원문을 저장하지 않지만(ConditionChangeLog 참고), 피드백을 남긴 턴에
    한해서만 예외를 둔다 — 테스트 중 "이 반응이 무엇에 대한 것인지" 확인할
    근거가 필요하다는 요청 때문. 대화 전체 로그와 달리 사용자가 명시적으로
    반응한 턴만 남으므로 노출 범위가 훨씬 좁다. 프론트가 텍스트를 못 찾거나
    안 보내면 None — 이 경우에도 rating 기록 자체는 그대로 유효하다.

    intent/comment는 같은 날 추가된 확장 필드다(D-068 연장). intent는
    step/prompt_version 등과 같은 성격 — 그 턴의 assistant_text 메시지가
    이미 들고 있는 값을 그대로 옮겨오는 것뿐이라 B는 검증하지 않는다.
    comment는 "싫어요" 사유로 사용자가 직접 쓴 자유 텍스트(선택) — user_input/
    assistant_message와 같은 위험 등급(자유 텍스트)으로 취급하고 같은 이유로
    nullable이다.
    """

    session_id: str
    run_id: str
    rating: Literal["like", "dislike"]
    user_input: str | None = None
    assistant_message: str | None = None
    intent: str | None = None
    comment: str | None = None
    recorded_at: datetime = Field(default_factory=now_kst)