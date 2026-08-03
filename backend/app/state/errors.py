"""Package B - State 저장소 관련 공통 오류.

역할: 저장소 구현체(InMemory/Supabase 등) 종류와 무관하게, B의 공개
진입점(service.py)에서 발생하는 예상 못한 예외를 프로젝트 표준 오류
형식(app.errors.AppError)으로 통일한다.

SupabaseRepositoryError처럼 이미 AppError인 예외는 그 자체로 의미가
있으므로 이 파일이 감싸지 않는다. service.py의 _wrap_store_errors가
AppError는 그대로 통과시키고 그 외의 예외만 이 클래스로 감싼다.
"""

from __future__ import annotations

from app.errors import AppError


class StateStoreError(AppError):
    """저장소 호출이 예상 못하게 실패했을 때. (Jira: B 영역 오류 공통 형식)"""

    def __init__(self, detail: str) -> None:
        super().__init__(
            code="state_store_error",
            message="상태 저장 중 문제가 발생했어요. 잠시 후 다시 시도해주세요.",
            status_code=502,
            retryable=True,
            provider="state_store",
            details={"upstream_detail": detail},
        )