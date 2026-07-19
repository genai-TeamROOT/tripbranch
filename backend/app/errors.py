"""TripBranch 백엔드 공통 애플리케이션 오류 타입.

역할: 서비스/라우터에서 발생한 의도된 오류를 표준 API 오류 응답으로 전달한다.
입력: 오류 코드, 사용자 메시지, HTTP 상태 코드, 재시도 가능 여부.
출력: FastAPI 예외 핸들러가 처리할 수 있는 AppError 인스턴스.
호출 시점: 도메인 검증 실패나 외부 provider 오류를 API 응답으로 바꿀 때 사용한다.
TODO: 실제 provider가 추가되면 원인 예외와 세부 details 필드를 확장한다.
"""

from __future__ import annotations


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
