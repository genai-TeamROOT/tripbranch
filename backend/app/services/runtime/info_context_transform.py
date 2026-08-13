"""A → C 변환: INFO 질의 전체.

context_transform.py(RECOMMEND)와 같은 원칙으로, 이 모듈은 INFO 질의 변환을
담당한다. question_type 8종(operating_hours/fee/parking/facility/event/
location_info/general_info/concentration) 모두 이 함수를 거친다(D-054/D-055,
backend/docs/package-a/info-question-types-handoff.md). info_context_schemas.py의
계약 문서 참고.
"""

from __future__ import annotations

from app.schemas import InfoPayload
from app.services.runtime.info_context_schemas import InfoContextRequest


def to_info_context_request(request_id: str, info: InfoPayload) -> InfoContextRequest:
    """A의 InfoPayload를 C에 보낼 InfoContextRequest로 변환한다."""

    return InfoContextRequest(
        request_id=request_id,
        place_name=info.place_name,
        place_context=info.place_context.value,
        question_type=info.question_type.value,
        specific_question=info.specific_question,
        visit_time=info.visit_time,
    )


__all__ = ["to_info_context_request"]
