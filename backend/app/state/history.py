"""Package B - 추천·거절 이력 관리.

계약 문서: docs/package-b/agent-state-contract-v1.md (3절)

이력은 append-only이며 기존 항목을 수정하지 않는다.
B는 place_id만 저장하고 장소 상세 정보를 보관하지 않는다.
"""

from app.state.schema import (
    RecommendationHistory,
    RecommendedItem,
    RejectedItem,
    now_kst,
)
from app.state.store import StateStore


def get_or_create(store: StateStore, session_id: str) -> RecommendationHistory:
    """이력을 조회하고, 없으면 빈 이력을 만든다."""
    history = store.get_history(session_id)
    if history is None:
        history = RecommendationHistory(session_id=session_id)
    return history


# ---------------------------------------------------------------- 기록

def record_recommended(
    store: StateStore,
    session_id: str,
    run_id: str,
    items: list[tuple[str, int]],
) -> int:
    """추천 결과를 기록한다. (계약 6.4절)

    items는 (place_id, rank) 목록이며, 실제로 노출이 확정된 것만 전달받는다.
    노출 여부를 아는 주체는 Agent Runtime이므로 호출도 Runtime이 담당한다.

    중복 place_id도 오류로 처리하지 않고 추가한다. (계약 3.5절)
    """
    history = get_or_create(store, session_id)
    shown_at = now_kst()

    for place_id, rank in items:
        history.recommended.append(
            RecommendedItem(
                place_id=place_id,
                run_id=run_id,
                rank=rank,
                shown_at=shown_at,
            )
        )

    history.updated_at = shown_at
    store.save_history(history)
    return len(items)


def record_rejected(
    store: StateStore,
    session_id: str,
    run_id: str,
    items: list[tuple[str, str | None]],
) -> int:
    """거절 장소를 기록한다.

    items는 (place_id, reason_code) 목록이다.
    reason_code는 Package A가 해석한 값을 그대로 저장하며 검증하지 않는다.

    추천 이력에 없는 place_id가 전달되어도 검증하지 않는다. (계약 3.3절)
    """
    history = get_or_create(store, session_id)
    rejected_at = now_kst()

    for place_id, reason_code in items:
        history.rejected.append(
            RejectedItem(
                place_id=place_id,
                run_id=run_id,
                reason_code=reason_code,
                rejected_at=rejected_at,
            )
        )

    history.updated_at = rejected_at
    store.save_history(history)
    return len(items)


# ---------------------------------------------------------------- 조회

def get_exclusion_place_ids(store: StateStore, session_id: str) -> list[str]:
    """추천 제외 대상 ID. (계약 3.3절)

    exclusion = recommended의 place_id ∪ rejected의 place_id

    중복은 제거하되, 결과가 실행마다 달라지지 않도록 등장 순서를 유지한다.
    (set을 그대로 반환하면 순서가 매번 바뀌어 로그 비교가 어렵다)
    """
    history = store.get_history(session_id)
    if history is None:
        return []

    seen: set[str] = set()
    result: list[str] = []

    for item in history.recommended:
        if item.place_id not in seen:
            seen.add(item.place_id)
            result.append(item.place_id)

    for item in history.rejected:
        if item.place_id not in seen:
            seen.add(item.place_id)
            result.append(item.place_id)

    return result


def get_shown_place_ids(store: StateStore, session_id: str) -> list[str]:
    """마지막 실행에서 노출된 장소 ID. rank 순. (계약 3.4절)

    COMPARE의 "첫 번째", "두 번째" 지시 표현은 방금 본 추천을 가리키므로
    누적 목록이 아니라 마지막 실행 기준이어야 한다.
    """
    history = store.get_history(session_id)
    if history is None or not history.recommended:
        return []

    last_run_id = history.recommended[-1].run_id
    items = [item for item in history.recommended if item.run_id == last_run_id]
    items.sort(key=lambda x: x.rank)

    return [item.place_id for item in items]


def get_last_recommended_run_id(store: StateStore, session_id: str) -> str | None:
    """마지막 추천이 발생한 실행 식별자."""
    history = store.get_history(session_id)
    if history is None or not history.recommended:
        return None
    return history.recommended[-1].run_id


def count_recommended(store: StateStore, session_id: str) -> int:
    """누적 노출 장소 수. 중복을 제거한 고유 개수."""
    history = store.get_history(session_id)
    if history is None:
        return 0
    return len({item.place_id for item in history.recommended})


def has_recommendation(store: StateStore, session_id: str) -> bool:
    """추천 이력이 1건 이상 존재하는지.

    Package A의 MODIFY / COMPARE 판정 전제 조건이다. (계약 6.3절)
    """
    history = store.get_history(session_id)
    return history is not None and len(history.recommended) > 0


# ---------------------------------------------------------------- 초기화

def clear_recommended(store: StateStore, session_id: str) -> None:
    """추천 이력만 비운다. 거절 이력은 유지한다. (history reset, 계약 5.5절)

    사용자가 명시적으로 거부한 장소는 어떤 초기화에서도 재노출하지 않는다.
    """
    history = store.get_history(session_id)
    if history is None:
        return

    history.recommended = []
    history.updated_at = now_kst()
    store.save_history(history)


def clear_all(store: StateStore, session_id: str) -> None:
    """추천·거절 이력을 모두 비운다. (full reset)"""
    store.delete_history(session_id)