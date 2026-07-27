"""Agent Runtime이 C(Tool Intelligence)/D(Recommendation)에 의존하는 최소 계약.

역할: Runtime 코드(agent_runtime.py)가 C/D의 구체 클래스를 직접 import하지 않고 이
Protocol만 거치도록 강제한다. A–C 요청·응답은 app.agent_context.schemas를 단일 계약으로
사용하며, 실제 C Service가 이 Protocol을 구현하면 stubs.py의 FakeToolProvider를 교체한다.
D 계약은 아직 확정 전이므로 RecommendationProvider는 임시 형태를 유지한다.
ToolProvider는 A-C Context Contract v0(docs/design/a-c-context-contract-draft.md)로 이미
확정됐다 — excluded_place_ids는 여기 없다. C는 외부 데이터 조회·정규화만 담당하고, 이전
노출·거절 후보 제외는 D Recommendation의 책임이라고 계약서 §2가 명시한다.
RecommendationProvider(D)는 아직 계약 확정 전이라 excluded_place_ids를 그대로 둔다.
TODO: D 계약이 확정되면 RecommendationProvider 시그니처가 바뀔 수 있다.
"""

from __future__ import annotations

from typing import Protocol

from app.agent_context.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    RecommendationContext,
)
from app.schemas import RecommendationResponse, UserConditions


class ToolProvider(Protocol):
    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        """조건에 맞는 위치·날씨·장소 후보 등을 공통 AgentContextResponse로 반환한다."""
        ...


class RecommendationProvider(Protocol):
    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
    ) -> RecommendationResponse:
        """조건과 Tool 결과를 바탕으로 최종 추천 결과를 반환한다."""
        ...
