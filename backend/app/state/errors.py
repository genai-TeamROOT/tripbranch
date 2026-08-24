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


class SessionOwnershipError(AppError):
    """인증된 신원과 세션에 저장된 소유자가 다를 때. (D-063 결정 2 후속, D-073)

    session_id만 알면(추측·유출) 남의 세션에 접근할 수 있던 문제를 닫는다.
    principal이 없는 요청(토큰 미전송)에는 이 오류를 내지 않는다 — Phase 4
    전면 필수화 전까지는 정상 경로이기 때문이다(session.verify_ownership 참고).
    401(신원 자체가 무효)과 구분하기 위해 403을 쓴다 — 토큰은 유효하지만
    이 세션에 대한 권한이 없다는 뜻이다.
    """

    def __init__(self) -> None:
        super().__init__(
            code="session_ownership_mismatch",
            message="이 세션에 접근할 권한이 없어요.",
            status_code=403,
        )