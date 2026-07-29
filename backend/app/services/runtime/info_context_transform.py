"""A → C 변환: INFO(question_type=concentration) 전용.

context_transform.py(RECOMMEND)와 같은 원칙으로, 이 모듈은 INFO의 혼잡도 질의
변환만 담당한다. info_context_schemas.py의 계약 초안 문서 참고.
"""

from __future__ import annotations

from app.schemas import InfoPayload
from app.services.runtime.info_context_schemas import InfoContextRequest


def to_info_context_request(request_id: str, info: InfoPayload) -> InfoContextRequest:
    """A의 InfoPayload를 C에 보낼 InfoContextRequest로 변환한다.

    question_type이 concentration이 아닌 InfoPayload로 호출하지 않는다 — 호출부
    (agent_runtime.py)가 이미 question_type == CONCENTRATION일 때만 이 함수를
    부른다.
    """

    return InfoContextRequest(
        request_id=request_id,
        place_name=info.place_name,
        place_context=info.place_context.value,
        visit_time=info.visit_time,
    )


__all__ = ["to_info_context_request"]
