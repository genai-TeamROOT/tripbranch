from datetime import UTC, datetime

import pytest

from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentResponse,
    CandidateEnrichmentResult,
    ConcentrationForecastData,
)
from app.agent_context.mappers import _operating_schedule
from app.agent_context.schemas import (
    ContextError,
    RecommendationContext,
    ResolvedLocation,
    WeatherForecast,
)
from app.agent_context.schemas import ContextValue as AgentContextValue
from app.agent_context.schemas import Coordinates as AgentCoordinates
from app.agent_context.schemas import PlaceCandidate as AgentPlaceCandidate
from app.concentration_policy import normalize_concentration
from app.domain.operating_hours import normalize_operating_schedule
from app.domain.scoring import CONCENTRATION_WEIGHTS
from app.domain.travel_route import TravelMode
from app.errors import AppError
from app.schemas import (
    Environment,
    RecommendationItem,
    RecommendationResponse,
    StatedWeather,
    UserConditions,
    WeatherIntent,
)
from app.services.recommendation_pipeline import (
    merge_prepared_recommendations,
    prepare_recommendation_from_context,
    rerank_with_concentration,
    resolve_requested_environment,
    run_recommendation_pipeline_from_context,
    score_prepared_recommendation,
)

_WEATHER_MISSING_WARNING = "현재 날씨 정보를 확인하지 못해 이 조건은 반영되지 않았어요."
_WEATHER_IGNORED_WARNING = "날씨 조건을 반영하지 않기로 하셔서 이번 추천에는 제외했어요."
_NO_NOTABLE_EXPLANATION_WARNING = (
    "이 장소는 특별히 강조할 만한 조건은 없지만, 조건에 맞아 추천했어요."
)


# --- run_recommendation_pipeline_from_context() ----------------------------
#
# A가 C에서 받은 RecommendationContext를 그대로 넘기는 D의 유일한 공개 진입점
# 검증([TECH-02] C-D 직접 의존 제거 및 RecommendationContext 경계 정리).
# D-03(추천 파이프라인 1차 E2E 통합)의 완료 기준(하드 필터, 이전 노출·거절
# 제외, 결정성)은 여기서 E2E로, score_candidates() 자체는 test_scoring.py가
# 단위 테스트로 커버한다.

_CONTEXT_VISIT_AT = datetime(2026, 7, 28, 15, 0, tzinfo=UTC)


def _context_location() -> AgentContextValue:
    return AgentContextValue(
        status="success",
        data=ResolvedLocation(
            requested_query="경복궁",
            resolved_name="경복궁",
            location=AgentCoordinates(latitude=37.5796, longitude=126.9770),
        ),
    )


def _context_place(place_id: str = "place-1") -> AgentPlaceCandidate:
    return AgentPlaceCandidate(
        place_id=place_id,
        name="근처 카페",
        category="cafe",
        location=AgentCoordinates(latitude=37.5806, longitude=126.9770),
        operating_schedule={"availability": "all_day", "rules": [], "closure_rules": []},
    )


@pytest.mark.asyncio
async def test_pipeline_from_context_builds_recommendation_with_explanations() -> None:
    context = RecommendationContext(
        location=_context_location(),
        weather=AgentContextValue(
            status="success",
            data=WeatherForecast(
                forecast_for=_CONTEXT_VISIT_AT,
                precipitation="rain",
            ),
        ),
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    assert len(response.recommendations) == 1
    assert response.unverified_recommendations == []
    assert response.recommendations[0].explanations


@pytest.mark.asyncio
async def test_split_pipeline_matches_compatibility_entrypoint() -> None:
    context = RecommendationContext(
        location=_context_location(),
        weather=AgentContextValue(
            status="success",
            data=WeatherForecast(
                forecast_for=_CONTEXT_VISIT_AT,
                precipitation="rain",
            ),
        ),
        places=AgentContextValue(
            status="success",
            data=[_context_place("place-1"), _context_place("place-2")],
        ),
    )

    prepared = await prepare_recommendation_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
    )
    split_response = await score_prepared_recommendation(
        prepared,
        search_radius_km=2.0,
    )
    compatible_response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    assert prepared.preparation.eligible_count == 2
    assert split_response.model_copy(update={"elapsed_ms": 0}) == (
        compatible_response.model_copy(update={"elapsed_ms": 0})
    )


@pytest.mark.asyncio
async def test_merge_prepared_recommendations_combines_unique_candidates() -> None:
    first_context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(status="success", data=[_context_place("place-1")]),
    )
    second_context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(
            status="success",
            data=[_context_place("place-1"), _context_place("place-2")],
        ),
    )
    first = await prepare_recommendation_from_context(
        first_context,
        visit_at=_CONTEXT_VISIT_AT,
    )
    second = await prepare_recommendation_from_context(
        second_context,
        visit_at=_CONTEXT_VISIT_AT,
    )

    merged = merge_prepared_recommendations([first, second])
    response = await score_prepared_recommendation(merged, search_radius_km=2.0)

    assert merged.preparation.input_count == 2
    assert [
        candidate.candidate.place_id
        for candidate in merged.preparation.eligible_candidates
    ] == ["place-1", "place-2"]
    assert {
        item.place_id
        for item in [*response.recommendations, *response.unverified_recommendations]
    } == {"place-1", "place-2"}


def test_merge_prepared_recommendations_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="병합할 준비 결과"):
        merge_prepared_recommendations([])


@pytest.mark.asyncio
async def test_pipeline_from_context_reports_weather_ignored_when_not_requested() -> None:
    """weather_intent=IGNORE면 C가 Weather Tool을 아예 실행하지 않아 weather가 없다.

    정상 흐름이므로 "확인하지 못했다"(조회 실패)와 다른 문구를 써야 한다.
    """
    context = RecommendationContext(
        location=_context_location(),
        weather=None,
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    warnings = response.recommendations[0].warnings
    assert _WEATHER_IGNORED_WARNING in warnings
    assert _WEATHER_MISSING_WARNING not in warnings


@pytest.mark.asyncio
async def test_pipeline_uses_stated_weather_when_context_weather_missing() -> None:
    """context.weather가 없어도(AVOID/ENJOY라 C가 조회를 생략) 발화 값으로 판정한다.

    D-051 판정 이관: RAIN + AVOID는 그대로 BAD, 카페(environment_type=unknown)라
    weather Feature는 BAD/unknown 조합 점수(0.60)가 된다(scoring.py
    `_WEATHER_FIT_TABLE`).
    """
    context = RecommendationContext(
        location=_context_location(),
        weather=None,
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        conditions=UserConditions(weather_intent=WeatherIntent.AVOID, weather=StatedWeather.RAIN),
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    item = response.recommendations[0]
    assert item.feature_scores["weather"] == 0.60
    assert item.weights_used["weather"] > 0


@pytest.mark.asyncio
async def test_pipeline_enjoy_flips_rain_to_good() -> None:
    """ENJOY + RAIN은 D-051 의도 재해석으로 GOOD이 된다("비 오는 날 산책하고 싶어")."""
    context = RecommendationContext(
        location=_context_location(),
        weather=None,
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        conditions=UserConditions(weather_intent=WeatherIntent.ENJOY, weather=StatedWeather.RAIN),
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    item = response.recommendations[0]
    assert item.feature_scores["weather"] == 0.85  # GOOD + unknown


@pytest.mark.asyncio
async def test_pipeline_avoid_without_stated_or_fetched_weather_reports_failure() -> None:
    """AVOID인데 발화도 못 뽑고 폴백 조회도 실패하면 opt-out이 아니라 실패다."""
    context = RecommendationContext(
        location=_context_location(),
        weather=None,
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        conditions=UserConditions(weather_intent=WeatherIntent.AVOID, weather=None),
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    warnings = response.recommendations[0].warnings
    assert _WEATHER_MISSING_WARNING in warnings
    assert _WEATHER_IGNORED_WARNING not in warnings


@pytest.mark.asyncio
async def test_pipeline_reports_ignored_when_conditions_say_ignore() -> None:
    """conditions가 있을 때는 IGNORE만 "제외했어요" 문구를 쓴다."""
    context = RecommendationContext(
        location=_context_location(),
        weather=None,
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        conditions=UserConditions(weather_intent=WeatherIntent.IGNORE),
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    warnings = response.recommendations[0].warnings
    assert _WEATHER_IGNORED_WARNING in warnings
    assert _WEATHER_MISSING_WARNING not in warnings


@pytest.mark.asyncio
async def test_pipeline_from_context_reports_weather_failure_when_lookup_failed() -> None:
    """조회를 시도했으나 실패한 경우에만 "확인하지 못했다"가 사실이다."""
    context = RecommendationContext(
        location=_context_location(),
        weather=AgentContextValue(
            status="unavailable",
            data=None,
            error=ContextError(
                code="unavailable", message="날씨를 조회하지 못했습니다.", retryable=True
            ),
        ),
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    warnings = response.recommendations[0].warnings
    assert _WEATHER_MISSING_WARNING in warnings
    assert _WEATHER_IGNORED_WARNING not in warnings


def _place_from_operating_hours_raw(raw: str) -> AgentPlaceCandidate:
    """운영시간 원문을 C의 실제 경로(파서 → 직렬화)에 그대로 태워 후보를 만든다.

    operating_schedule dict를 손으로 써서 검증하면 C가 실제로는 만들지 않는 입력
    형태를 통과시켜, 프로덕션에서만 깨지는 결함을 놓친다 — `_operating_schedule()`이
    close_time을 "%H:%M"으로 자르는 탓에 자정 마감 표식(time.max)이 지워지는 게
    그 예다. 원문은 Supabase places.operating_hours_raw에 실제로 있는 값들이다.
    """
    schedule = normalize_operating_schedule(
        content_type_id="12", operating_hours=raw, rest_date=None
    )
    return AgentPlaceCandidate(
        place_id="place-1",
        name="근처 카페",
        category="cafe",
        location=AgentCoordinates(latitude=37.5806, longitude=126.9770),
        operating_schedule=_operating_schedule(schedule),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operating_hours_raw", "expected"),
    [
        # 프론트가 "09:00~18:00 (N시간 남음)"을 그릴 수 있도록 당일 구간을 내려준다.
        # remaining_minutes만으로는 "언제부터"를 알 수 없어 추가된 필드다.
        ("09:00~18:00", "09:00~18:00"),
        ("09:00-18:00", "09:00~18:00"),
        ("09:00~18:00 (입장 마감 17:30)", "09:00~18:00"),
        # 24시간 개방을 "00:00~23:59"로 쓰면 마감이 임박한 것처럼 읽힌다.
        ("상시 개방", "24시간"),
        ("00:00~24:00", "24시간"),
        # 원문의 24:00을 "23:59"로 쓰면 1분 일찍 닫는 것처럼 읽힌다.
        ("10:30~24:00", "10:30~24:00"),
        ("01:00~24:00", "01:00~24:00"),
        # 계절별 규칙에서는 방문 월(7월)에 해당하는 구간을 고른다.
        ("[2월~5월] 09:00~18:00<br>\n[6월~8월] 09:00~18:30", "09:00~18:30"),
    ],
)
async def test_operating_hours_display_matches_source_text(
    operating_hours_raw: str, expected: str
) -> None:
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(
            status="success", data=[_place_from_operating_hours_raw(operating_hours_raw)]
        ),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    assert response.recommendations[0].operating_hours_display == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("operating_hours_raw", ["점포 별로 상이함", "15:00"])
async def test_operating_hours_display_is_none_when_text_is_unparsable(
    operating_hours_raw: str,
) -> None:
    """해석 못 한 원문은 unknown이라 unverified로 빠지고 표시할 구간도 없다."""
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(
            status="success", data=[_place_from_operating_hours_raw(operating_hours_raw)]
        ),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    assert response.recommendations == []
    assert response.unverified_recommendations[0].operating_hours_display is None


@pytest.mark.asyncio
async def test_operating_hours_display_is_none_when_schedule_missing() -> None:
    """운영시간 자체가 안 넘어온 후보도 표시할 구간이 없다."""
    place = AgentPlaceCandidate(
        place_id="place-1",
        name="근처 카페",
        category="cafe",
        location=AgentCoordinates(latitude=37.5806, longitude=126.9770),
        operating_schedule=None,
    )
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(status="success", data=[place]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    assert response.recommendations == []
    assert response.unverified_recommendations[0].operating_hours_display is None


@pytest.mark.asyncio
async def test_pipeline_from_context_returns_empty_when_places_have_no_data() -> None:
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(status="no_data", data=[]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    assert response.recommendations == []
    assert response.unverified_recommendations == []
    assert response.excluded_all_closed is False


@pytest.mark.asyncio
async def test_pipeline_from_context_reports_excluded_all_closed_when_only_closed_places() -> None:
    # _CONTEXT_VISIT_AT은 15:00. 09:00~14:00 영업은 이 시각엔 이미 마감이라
    # 결과가 0건이 되고, 유일한 제외 사유가 폐점이라 excluded_all_closed=True다.
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(
            status="success", data=[_place_from_operating_hours_raw("09:00~14:00")]
        ),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    assert response.recommendations == []
    assert response.unverified_recommendations == []
    assert response.excluded_all_closed is True


@pytest.mark.asyncio
async def test_pipeline_from_context_ignore_operating_hours_includes_closed_places() -> None:
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(
            status="success", data=[_place_from_operating_hours_raw("09:00~14:00")]
        ),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
        ignore_operating_hours=True,
    )

    assert len(response.unverified_recommendations) == 1
    assert response.recommendations == []
    assert response.excluded_all_closed is False


@pytest.mark.asyncio
async def test_pipeline_from_context_raises_when_places_unavailable() -> None:
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(
            status="unavailable",
            error=ContextError(
                code="place_search_failed", message="장소 조회 실패", retryable=True
            ),
        ),
    )

    with pytest.raises(AppError) as exc_info:
        await run_recommendation_pipeline_from_context(
            context,
            visit_at=_CONTEXT_VISIT_AT,
            search_radius_km=2.0,
        )

    assert exc_info.value.code == "place_search_failed"


@pytest.mark.asyncio
async def test_pipeline_from_context_raises_when_location_missing() -> None:
    context = RecommendationContext(location=None, places=None)

    with pytest.raises(AppError) as exc_info:
        await run_recommendation_pipeline_from_context(
            context,
            visit_at=_CONTEXT_VISIT_AT,
            search_radius_km=2.0,
        )

    assert exc_info.value.code == "location_unavailable"


@pytest.mark.asyncio
async def test_pipeline_from_context_raises_when_context_is_none() -> None:
    """AgentContextResponse.status가 needs_clarification/unsupported/unavailable이면
    AgentContextResponse.context 자체가 None일 수 있다 — 이 경우도 AppError로
    처리해야 한다(속성 접근 시 AttributeError가 그대로 터지면 안 된다).
    """
    with pytest.raises(AppError) as exc_info:
        await run_recommendation_pipeline_from_context(
            None,
            visit_at=_CONTEXT_VISIT_AT,
            search_radius_km=2.0,
        )

    assert exc_info.value.code == "context_unavailable"


@pytest.mark.asyncio
async def test_pipeline_from_context_excludes_shown_place_ids() -> None:
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(
            status="success",
            data=[_context_place("place-1"), _context_place("place-2")],
        ),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
        shown_place_ids=frozenset({"place-1"}),
    )

    place_ids = {item.place_id for item in response.recommendations}
    assert place_ids == {"place-2"}


@pytest.mark.asyncio
async def test_pipeline_from_context_is_deterministic_for_identical_input() -> None:
    context = RecommendationContext(
        location=_context_location(),
        weather=AgentContextValue(
            status="success",
            data=WeatherForecast(
                forecast_for=_CONTEXT_VISIT_AT,
                precipitation="none",
                sky="clear",
            ),
        ),
        places=AgentContextValue(
            status="success",
            data=[_context_place("place-1"), _context_place("place-2")],
        ),
    )

    def _run():
        return run_recommendation_pipeline_from_context(
            context,
            visit_at=_CONTEXT_VISIT_AT,
            search_radius_km=2.0,
        )

    response_1 = await _run()
    response_2 = await _run()

    def _normalize(response):
        return [
            (item.place_id, item.score, item.weights_used, tuple(item.warnings))
            for item in response.recommendations + response.unverified_recommendations
        ]

    assert _normalize(response_1) == _normalize(response_2)


# --- rerank_with_concentration() (D-040, 2차 Scoring) ------------------------
#
# 1차 결과(RecommendationResponse, 이미 5개로 좁혀진 상태)에 concentration
# Feature를 더해 재채점하는 D의 신규 진입점. weather/remaining_operating_time을
# 둘 다 결측(None)으로 고정해 순수하게 "distance vs concentration"만으로
# 재순위가 실제로 뒤집히는지 검증한다.


def _first_pass_item(
    place_id: str,
    *,
    distance_km: float,
    distance_score: float,
    operating_hours_display: str | None = None,
    travel_distance_m: int | None = None,
    travel_duration_seconds: int | None = None,
    travel_mode: TravelMode | None = None,
    taste_score: float | None = None,
) -> RecommendationItem:
    # taste_score가 None이면 1차가 취향을 아예 안 쓴 실행이라 키 자체가 없다 —
    # 결측(None 값)과 구분해야 2차 가중치 조립이 같은 판단을 내린다.
    feature_scores: dict[str, float | None] = {
        "weather": None,
        "remaining_operating_time": None,
        "distance": distance_score,
    }
    if taste_score is not None:
        feature_scores["taste"] = taste_score
    return RecommendationItem(
        place_id=place_id,
        name=f"장소-{place_id}",
        category="cafe",
        distance_km=distance_km,
        remaining_minutes=None,
        operating_hours_display=operating_hours_display,
        travel_distance_m=travel_distance_m,
        travel_duration_seconds=travel_duration_seconds,
        travel_mode=travel_mode,
        environment_type="indoor",
        recommendation_reason="테스트용 1차 추천입니다.",
        explanations=[],
        warnings=[],
        score=distance_score,
        feature_scores=feature_scores,
        weights_used={"distance": 1.0},
    )


def _concentration_result(place_id: str, *, rate: float) -> CandidateEnrichmentResult:
    normalized = normalize_concentration(rate)
    return CandidateEnrichmentResult(
        place_id=place_id,
        name=f"장소-{place_id}",
        latitude=37.58,
        longitude=126.97,
        status="success",
        concentration=[
            ConcentrationForecastData(
                place_name=f"장소-{place_id}",
                forecast_date=None,
                concentration_rate=rate,
                concentration_level=normalized.level,
                concentration_label=normalized.label,
            )
        ],
    )


def _no_data_result(place_id: str) -> CandidateEnrichmentResult:
    return CandidateEnrichmentResult(
        place_id=place_id,
        name=f"장소-{place_id}",
        latitude=37.58,
        longitude=126.97,
        status="no_data",
        concentration=[],
    )


@pytest.mark.asyncio
async def test_rerank_with_concentration_keeps_taste_from_first_pass() -> None:
    """1차에서 취향으로 후보를 골랐으면 2차 순위에도 취향이 남아야 한다.

    place-1은 훨씬 가깝고(1차 1위) place-2는 멀지만 취향 근거가 강하다. 혼잡도는
    두 곳이 같아서 순위를 가르지 못한다 — 그래서 순위가 뒤집히면 그건 취향이
    반영됐다는 뜻이다.

    2026-08-20 이전에는 뒤집히지 않았다. 2차가 CONCENTRATION_WEIGHTS를 그대로
    썼는데 그 상수에 taste 키가 없어서, 취향 점수가 feature_scores에는 남아 있는
    채로 가중합에서만 빠졌다. 가중치 합이 1.0이라 결측 재분배도 안 걸렸다.
    """
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item("place-1", distance_km=0.1, distance_score=0.95, taste_score=0.0),
            _first_pass_item("place-2", distance_km=1.2, distance_score=0.4, taste_score=1.0),
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-taste",
        status="success",
        candidates=[
            _concentration_result("place-1", rate=50.0),
            _concentration_result("place-2", rate=50.0),
        ],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=False)

    assert [item.place_id for item in result.recommendations] == ["place-2", "place-1"]
    for item in result.recommendations:
        assert "taste" in item.weights_used
        assert sum(item.weights_used.values()) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_rerank_without_taste_does_not_invent_the_axis() -> None:
    """취향을 말하지 않은 요청은 2차에도 taste 키가 없어야 한다."""
    first_pass = RecommendationResponse(
        recommendations=[_first_pass_item("place-1", distance_km=0.1, distance_score=0.95)],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-no-taste",
        status="success",
        candidates=[_concentration_result("place-1", rate=50.0)],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=False)

    item = result.recommendations[0]
    assert "taste" not in item.weights_used
    assert "taste" not in item.feature_scores


@pytest.mark.asyncio
async def test_rerank_with_concentration_avoid_prefers_quiet_place() -> None:
    """place-1이 더 가깝지만(1차 1위) 훨씬 붐비고, place-2는 멀지만 한적하다.

    AVOID(seek=False)면 2차 Scoring 후 순위가 뒤집혀야 한다.
    """
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item("place-1", distance_km=0.1, distance_score=0.95),
            _first_pass_item("place-2", distance_km=1.2, distance_score=0.4),
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-1",
        status="success",
        candidates=[
            _concentration_result("place-1", rate=95.0),
            _concentration_result("place-2", rate=5.0),
        ],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=False)

    assert [item.place_id for item in result.recommendations] == ["place-2", "place-1"]
    quiet_item = result.recommendations[0]
    assert "지금 이 근처는 한적한 편이에요." in quiet_item.explanations


@pytest.mark.asyncio
async def test_rerank_with_concentration_seek_prefers_crowded_place() -> None:
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item("place-1", distance_km=0.1, distance_score=0.95),
            _first_pass_item("place-2", distance_km=1.2, distance_score=0.4),
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-2",
        status="success",
        candidates=[
            _concentration_result("place-1", rate=5.0),
            _concentration_result("place-2", rate=95.0),
        ],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=True)

    assert [item.place_id for item in result.recommendations] == ["place-2", "place-1"]


@pytest.mark.asyncio
async def test_rerank_with_concentration_handles_ten_candidates() -> None:
    """SCHEDULE-03: 10개로 넘어온 1차 결과도 2차 Scoring이 전부 처리해야 한다
    (하드코딩된 5개 제한이 없는지 확인)."""
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item(f"place-{i}", distance_km=0.1 * i, distance_score=0.9 - 0.05 * i)
            for i in range(10)
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-10",
        status="success",
        candidates=[_concentration_result(f"place-{i}", rate=50.0) for i in range(10)],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=False)

    assert len(result.recommendations) == 10


@pytest.mark.asyncio
async def test_rerank_with_concentration_handles_partial_no_data() -> None:
    """concentration이 일부 후보만 결측(no_data)이어도 크래시 없이 개별 재분배된다."""
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item("place-1", distance_km=0.1, distance_score=0.95),
            _first_pass_item("place-2", distance_km=1.2, distance_score=0.4),
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-3",
        status="partial",
        candidates=[
            _concentration_result("place-1", rate=50.0),
            _no_data_result("place-2"),
        ],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=True)

    place_ids = {item.place_id for item in result.recommendations}
    assert place_ids == {"place-1", "place-2"}
    place_2 = next(item for item in result.recommendations if item.place_id == "place-2")
    assert place_2.feature_scores.get("concentration") is None
    assert "concentration" not in place_2.weights_used


@pytest.mark.asyncio
async def test_rerank_with_concentration_preserves_unverified_split() -> None:
    first_pass = RecommendationResponse(
        recommendations=[_first_pass_item("place-1", distance_km=0.1, distance_score=0.95)],
        unverified_recommendations=[
            _first_pass_item("place-2", distance_km=1.2, distance_score=0.4)
        ],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-4",
        status="success",
        candidates=[
            _concentration_result("place-1", rate=50.0),
            _concentration_result("place-2", rate=50.0),
        ],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=True)

    assert [item.place_id for item in result.recommendations] == ["place-1"]
    assert [item.place_id for item in result.unverified_recommendations] == ["place-2"]


@pytest.mark.asyncio
async def test_rerank_with_concentration_preserves_operating_hours_display() -> None:
    """2차는 RecommendationItem을 새로 만든다 — 운영 구간을 옮겨 담지 않으면
    혼잡도 재순위를 탄 요청에서만 이 필드가 조용히 사라진다.
    """
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item(
                "place-1",
                distance_km=0.1,
                distance_score=0.95,
                operating_hours_display="09:00~18:00",
            )
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-5",
        status="success",
        candidates=[_concentration_result("place-1", rate=50.0)],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=True)

    assert result.recommendations[0].operating_hours_display == "09:00~18:00"


# --- resolve_requested_environment() ---------------------------------------


@pytest.mark.parametrize(
    ("environment", "weather_intent", "expected"),
    [
        (Environment.INDOOR, WeatherIntent.NO_MENTION, "indoor"),
        (Environment.OUTDOOR, WeatherIntent.NO_MENTION, "outdoor"),
        (Environment.INDOOR, WeatherIntent.IGNORE, "indoor"),
        (Environment.ANY, WeatherIntent.NO_MENTION, "any"),
        (None, WeatherIntent.NO_MENTION, None),
        # 날씨를 함께 언급한 경로는 기존 날씨 판정이 이미 실내/실외를 반영한다.
        (Environment.INDOOR, WeatherIntent.AVOID, None),
        (Environment.OUTDOOR, WeatherIntent.ENJOY, None),
    ],
)
def test_resolve_requested_environment_precedence(
    environment: Environment | None,
    weather_intent: WeatherIntent,
    expected: str | None,
) -> None:
    conditions = UserConditions(environment=environment, weather_intent=weather_intent)
    assert resolve_requested_environment(conditions) == expected


def test_resolve_requested_environment_without_conditions() -> None:
    assert resolve_requested_environment(None) is None


@pytest.mark.asyncio
async def test_requested_environment_run_has_no_weather_warning() -> None:
    """요청 환경으로 채점한 실행에는 weather 키 자체가 없다.

    이걸 결측으로 읽으면 날씨를 조회했는데도 "확인하지 못했다"는 warning이
    붙는다 — 존재하지 않는 Feature와 결측을 구분해야 한다.
    """
    context = RecommendationContext(
        location=_context_location(),
        weather=AgentContextValue(
            status="success",
            data=WeatherForecast(forecast_for=_CONTEXT_VISIT_AT, sky="clear"),
        ),
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
        conditions=UserConditions(
            environment=Environment.INDOOR, weather_intent=WeatherIntent.NO_MENTION
        ),
    )

    item = response.recommendations[0]
    assert "environment" in item.feature_scores
    assert "weather" not in item.feature_scores
    assert _WEATHER_MISSING_WARNING not in item.warnings
    assert _WEATHER_IGNORED_WARNING not in item.warnings


@pytest.mark.asyncio
async def test_rerank_keeps_environment_feature_in_second_pass() -> None:
    """1차가 요청 환경으로 채점했으면 2차 가중치도 그 키를 따라가야 한다.

    안 맞추면 environment 점수가 합산에서 통째로 빠지고, 존재하지도 않는
    weather가 결측으로 잡혀 재분배까지 일어난다.
    """
    environment_item = _first_pass_item("place-1", distance_km=0.1, distance_score=0.95)
    environment_item = environment_item.model_copy(
        update={
            # remaining_minutes와 그 Feature 점수는 함께 있거나 함께 없어야 한다
            # (explanation.py가 그 짝을 전제로 문장을 만든다).
            "remaining_minutes": 240.0,
            "feature_scores": {
                "environment": 1.0,
                "remaining_operating_time": 1.0,
                "distance": 0.95,
            },
        }
    )
    first_pass = RecommendationResponse(
        recommendations=[environment_item],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-env",
        status="success",
        candidates=[_concentration_result("place-1", rate=5.0)],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=False)

    item = result.recommendations[0]
    assert item.feature_scores["environment"] == 1.0
    assert "weather" not in item.weights_used
    assert item.weights_used["environment"] == CONCENTRATION_WEIGHTS["weather"]
    assert sum(item.weights_used.values()) == pytest.approx(1.0)
    assert "요청하신 실내 장소예요." in item.explanations


@pytest.mark.asyncio
async def test_rerank_with_concentration_preserves_travel_measurements() -> None:
    """2차는 RecommendationItem을 새로 만든다 — 실측 이동 정보를 옮겨 담지 않으면
    혼잡도 재순위를 탄 요청에서만 이 필드가 조용히 사라진다. mode도 함께 옮긴다:
    수치만 남고 mode가 빠지면 프론트가 무슨 수단인지 다시 추측하게 된다.
    """
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item(
                "place-1",
                distance_km=0.1,
                distance_score=0.95,
                travel_distance_m=620,
                travel_duration_seconds=530,
                travel_mode=TravelMode.WALKING,
            )
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-walk",
        status="success",
        candidates=[_concentration_result("place-1", rate=50.0)],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=True)

    item = result.recommendations[0]
    assert item.travel_distance_m == 620
    assert item.travel_duration_seconds == 530
    assert item.travel_mode is TravelMode.WALKING
