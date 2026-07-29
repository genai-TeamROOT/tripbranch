"""A → C 변환의 유일한 지점(A-C Context Contract v0).

역할: A의 UserConditions(app.schemas, enum 타입)를 C의 AgentContextRequest
(app.agent_context.schemas, Literal 타입)로 변환한다.
app.services.interpret.state_transform.to_user_conditions()가 B↔A 변환을 전담하는
것과 같은 원칙으로, 이 모듈은 A↔C 변환만 전담한다 — 나중에 D 계약이 확정되면 A↔D
변환 함수가 또 하나 늘어날 텐데, 그때도 A↔B/A↔C/A↔D 세 변환 지점을 서로 섞지 않는다.
"""

from __future__ import annotations

from app.agent_context.schemas import AgentContextRequest
from app.agent_context.schemas import UserConditions as ContextUserConditions
from app.schemas import UserConditions


def to_agent_context_request(request_id: str, conditions: UserConditions) -> AgentContextRequest:
    """A의 UserConditions(app.schemas)를 C의 AgentContextRequest로 변환한다.

    필드 이름·개수가 같으면 dict 왕복으로 충분하다(A-C Context Contract v0
    0단계 검토 확인 — enum 값은 model_dump() 후 Literal/str 필드로 재검증하면 그대로
    맞물린다). 주의: conditions.weather는 사용자가 말한 5단계 날씨(rain/snow/hot/cold/
    good)다. api_context.api_weather(3단계 good/neutral/bad, Provider 정규화 값)를
    여기 섞어 넣지 않는다 — 계약 문서 §5.2가 명시한 원칙이고, 이 함수의 입력 타입 자체가
    api_context를 받지 않으므로 구조적으로도 섞일 수 없다.

    ContextUserConditions(C 소유)는 StrictModel(extra="forbid")이라, A가 새 필드를
    먼저 추가하고 C가 아직 그 필드를 받아들이지 않는 과도기에는 model_dump()를 그대로
    넘기면 ValidationError가 난다(예: concentration_intent, concentration-conditions.md
    §2.1 — C가 필드를 추가하기 전까지의 상태). C가 아는 필드만 골라 넘겨서 이 과도기를
    안전하게 넘긴다 — C가 필드를 추가하면 자동으로 함께 전달되기 시작하므로, 그 시점에
    이 함수를 다시 고칠 필요는 없다.
    """

    known_fields = ContextUserConditions.model_fields.keys()
    payload = {
        key: value for key, value in conditions.model_dump().items() if key in known_fields
    }
    context_conditions = ContextUserConditions.model_validate(payload)
    return AgentContextRequest(
        request_id=request_id, intent="RECOMMEND", conditions=context_conditions
    )


__all__ = ["to_agent_context_request"]
