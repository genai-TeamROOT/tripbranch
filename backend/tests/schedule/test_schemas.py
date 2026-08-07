"""일정 편성 모듈 스키마 검증 테스트.

계약 문서: docs/design/int-07-schedule.md 6.1~6.2절, 7절
"""

from __future__ import annotations

from app.schedule.schemas import SchedulePlanningRequest
from app.schemas import (
    AgentResponse,
    Intent,
    LLMOutput,
    OutputStatus,
    RecommendationItem,
    RecommendationResponse,
    ScheduleItem,
    ScheduleResult,
    UserConditions,
)
from app.state.schema import UserConditions as StateUserConditions
from app.state.service import ApiContextView, StateApplyResponse


def _sample_recommendation_item(place_id: str = "place-1") -> RecommendationItem:
    return RecommendationItem(
        place_id=place_id,
        name="연남동 카페 A",
        category="cafe",
        distance_km=0.4,
        remaining_minutes=120,
        environment_type="indoor",
        recommendation_reason="근처라서 추천해요.",
        explanations=[],
        warnings=[],
        score=0.9,
        feature_scores={},
        weights_used={},
    )


def _sample_state_response() -> StateApplyResponse:
    return StateApplyResponse(
        session_id="sess_test",
        run_id="run_test",
        session_created=True,
        user_conditions=StateUserConditions(),
        api_context=ApiContextView(),
        condition_version=1,
        condition_changed=False,
    )


class TestScheduleResultSchema:
    """docs/design/int-07-schedule.md 6.2절 — 출력 스키마."""

    def test_basis_note_필드가_포함된다(self):
        result = ScheduleResult(
            items=[
                ScheduleItem(
                    order=1,
                    place_id="place-1",
                    place_name="연남동 카페 A",
                    estimated_arrival="15:00",
                    estimated_duration_min=60,
                    travel_to_next_min=15,
                    reason="도보 이동 시작점에 가까워요.",
                )
            ],
            total_duration_min=180,
            route_summary="연남동 순으로 이동 거리를 최소화했어요.",
            basis_note="이 정보는 15:00 기준으로 계산됐어요.",
        )
        assert result.basis_note == "이 정보는 15:00 기준으로 계산됐어요."
        assert result.items[0].order == 1
        assert result.items[0].travel_to_next_min == 15


class TestAgentResponseScheduleField:
    """AgentResponse.schedule이 SCHEDULE일 때만 채워지고 기존 흐름엔 영향 없어야 한다."""

    def test_schedule_기본값은_None이다(self):
        response = AgentResponse(
            llm_output=LLMOutput(intent=Intent.SCHEDULE, status=OutputStatus.COMPLETE),
            state=_sample_state_response(),
            message="일정 추천 기능은 아직 준비 중이에요.",
        )
        assert response.schedule is None

    def test_schedule_필드에_ScheduleResult를_담을_수_있다(self):
        result = ScheduleResult(items=[], total_duration_min=0, route_summary="", basis_note="")
        response = AgentResponse(
            llm_output=LLMOutput(intent=Intent.SCHEDULE, status=OutputStatus.COMPLETE),
            state=_sample_state_response(),
            schedule=result,
            message="일정 테스트",
        )
        assert response.schedule is result

    def test_recommendations만_있는_기존_응답도_그대로_생성된다(self):
        """RECOMMEND/MODIFY 흐름 회귀 없음 확인 — schedule 필드 추가가 기존
        recommendations 단독 구성을 깨지 않는지 본다."""
        response = AgentResponse(
            llm_output=LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE),
            state=_sample_state_response(),
            recommendations=RecommendationResponse(
                recommendations=[_sample_recommendation_item()],
                unverified_recommendations=[],
                elapsed_ms=10.0,
            ),
            message="추천 테스트",
        )
        assert response.schedule is None
        assert response.recommendations is not None
        assert len(response.recommendations.recommendations) == 1


class TestSchedulePlanningRequestSchema:
    """docs/design/int-07-schedule.md 6.1절 — 입력 스키마."""

    def test_candidates는_RecommendationItem_리스트다(self):
        request = SchedulePlanningRequest(
            candidates=[
                _sample_recommendation_item("place-1"),
                _sample_recommendation_item("place-2"),
            ],
            conditions=UserConditions(),
            visit_datetime=None,
            pairwise_distances_km={("place-1", "place-2"): 0.6},
        )
        assert len(request.candidates) == 2
        assert isinstance(request.candidates[0], RecommendationItem)
        assert request.pairwise_distances_km[("place-1", "place-2")] == 0.6

    def test_visit_datetime은_생략_가능하다(self):
        request = SchedulePlanningRequest(
            candidates=[],
            conditions=UserConditions(),
            pairwise_distances_km={},
        )
        assert request.visit_datetime is None
