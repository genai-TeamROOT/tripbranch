"""일정 구간 이동시간 확정 경로. (TP-216)"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.schedule_travel import (
    ScheduleTravelCandidate,
    ScheduleTravelEdge,
    TravelConfidence,
)
from app.domain.travel_route import (
    GeoCoordinate,
    RouteDestination,
    RouteSource,
    RouteStatus,
    TravelMode,
    TravelRoute,
    TravelRouteBatch,
)
from app.place_search_policy import (
    NON_WALKING_SPEED_KM_PER_MINUTE,
    WALKING_SPEED_KM_PER_MINUTE,
)
from app.providers.contracts import ProviderSource, ProviderStatus, provider_result
from app.schedule.travel import (
    NON_WALKING_SPEED_MPS,
    WALKING_SPEED_MPS,
    consecutive_pairs,
    resolve_schedule_travel_edges,
    travel_minutes_from_edges,
)
from app.schemas import Transport, UserConditions
from app.tools.travel_route import TravelRouteProviders, TravelRouteTool


def _candidate(place_id: str, longitude: float) -> ScheduleTravelCandidate:
    return ScheduleTravelCandidate(
        place_id=place_id,
        coordinate=GeoCoordinate(latitude=37.5, longitude=longitude),
    )


def _edge(from_id: str, to_id: str, minutes: int) -> ScheduleTravelEdge:
    return ScheduleTravelEdge(
        from_place_id=from_id,
        to_place_id=to_id,
        mode=TravelMode.WALKING,
        status=RouteStatus.SUCCESS,
        source=RouteSource.KAKAO_WALKING,
        duration_min=minutes,
        distance_m=1000,
        confidence=TravelConfidence.HIGH,
    )


_MEASURED_SOURCE = {
    TravelMode.WALKING: RouteSource.KAKAO_WALKING,
    TravelMode.DRIVING: RouteSource.NAVER_DRIVING,
    TravelMode.TRANSIT: RouteSource.KAKAO_TRANSIT,
}


class _MeasuringRouteProvider:
    """실측이 성공한 상황. 구간마다 고정 소요시간을 돌려준다."""

    def __init__(self, duration_seconds: int = 600) -> None:
        self._duration_seconds = duration_seconds

    async def get_routes(
        self,
        origin: GeoCoordinate,
        destinations: tuple[RouteDestination, ...],
        *,
        mode: TravelMode = TravelMode.WALKING,
        radius_m: int | None = None,
    ):
        routes = tuple(
            TravelRoute(
                place_id=item.place_id,
                mode=mode,
                status=RouteStatus.SUCCESS,
                source=_MEASURED_SOURCE[mode],
                distance_m=1_200,
                duration_seconds=self._duration_seconds,
            )
            for item in destinations
        )
        return provider_result(
            TravelRouteBatch(routes=routes),
            source=ProviderSource.KAKAO_WALKING_ROUTE,
            status=ProviderStatus.SUCCESS,
        )


def _tool(
    provider: object | None = None,
    modes=(TravelMode.WALKING, TravelMode.TRANSIT),
) -> TravelRouteTool:
    primary = provider or _MeasuringRouteProvider()
    return TravelRouteTool(
        {mode: TravelRouteProviders(primary=primary) for mode in modes}
    )


class Test속도_상수:
    def test_반경_산정과_같은_가정을_환산한다(self) -> None:
        """Settings 값(1.2 / 5.5 mps)이 아니라 place_search_policy를 쓴다.

        차이가 3% 남짓이라 화면으로도 다른 테스트로도 안 잡힌다 — 여기서 못 박는다.
        """

        assert WALKING_SPEED_MPS == pytest.approx(WALKING_SPEED_KM_PER_MINUTE * 1000 / 60)
        assert NON_WALKING_SPEED_MPS == pytest.approx(
            NON_WALKING_SPEED_KM_PER_MINUTE * 1000 / 60
        )

    def test_Settings_기본값과_다르다(self) -> None:
        settings = Settings()
        assert WALKING_SPEED_MPS != pytest.approx(settings.walking_speed_mps)
        assert NON_WALKING_SPEED_MPS != pytest.approx(settings.driving_speed_mps)


class Test구간_뽑기:
    def test_방문_순서의_인접_쌍만_만든다(self) -> None:
        pairs = consecutive_pairs(["a", "b", "c"])
        assert [(p.from_place_id, p.to_place_id) for p in pairs] == [("a", "b"), ("b", "c")]

    def test_자기_자신으로_가는_구간은_버린다(self) -> None:
        assert consecutive_pairs(["a", "a", "b"]) == (
            *consecutive_pairs(["a", "b"]),
        )

    def test_한_곳이면_구간이_없다(self) -> None:
        assert consecutive_pairs(["a"]) == ()


class Test구간표_읽기:
    def test_방향을_지킨다(self) -> None:
        resolve = travel_minutes_from_edges([_edge("a", "b", 12)])
        assert resolve("a", "b") == 12
        # 실측은 왕복이 다를 수 있어 반대 방향으로 대신 답하지 않는다.
        assert resolve("b", "a") is None

    def test_표에_없으면_None이다(self) -> None:
        resolve = travel_minutes_from_edges([_edge("a", "b", 12)])
        assert resolve("a", "c") is None

    def test_0분_구간도_최소_1분으로_올린다(self) -> None:
        resolve = travel_minutes_from_edges([_edge("a", "b", 0)])
        assert resolve("a", "b") == 1


class Test구간_이동정보_확정:
    _conditions = UserConditions(transport=Transport.WALK)

    @pytest.mark.asyncio
    async def test_좌표가_없으면_빈_결과다(self) -> None:
        edges = await resolve_schedule_travel_edges(
            candidates=[],
            place_ids=["a", "b"],
            conditions=self._conditions,
            settings=Settings(),
            travel_route_tool=None,
        )
        assert edges == ()

    @pytest.mark.asyncio
    async def test_한_곳뿐이면_구간을_만들지_않는다(self) -> None:
        edges = await resolve_schedule_travel_edges(
            candidates=[_candidate("a", 127.0)],
            place_ids=["a"],
            conditions=self._conditions,
            settings=Settings(),
            travel_route_tool=None,
        )
        assert edges == ()

    @pytest.mark.asyncio
    async def test_경로_Tool이_없으면_추정만_돌려준다(self) -> None:
        edges = await resolve_schedule_travel_edges(
            candidates=[_candidate("a", 127.0), _candidate("b", 127.01)],
            place_ids=["a", "b"],
            conditions=self._conditions,
            settings=Settings(),
            travel_route_tool=None,
        )
        assert len(edges) == 1
        assert edges[0].source is RouteSource.STRAIGHT_LINE_ESTIMATE
        assert edges[0].confidence is TravelConfidence.LOW

    @pytest.mark.asyncio
    async def test_경로_Tool이_있으면_실측이_추정을_덮는다(self) -> None:
        edges = await resolve_schedule_travel_edges(
            candidates=[_candidate("a", 127.0), _candidate("b", 127.01)],
            place_ids=["a", "b"],
            conditions=self._conditions,
            settings=Settings(),
            travel_route_tool=_tool(),
        )
        assert len(edges) == 1
        assert edges[0].source is RouteSource.KAKAO_WALKING
        assert edges[0].confidence is TravelConfidence.HIGH
        assert edges[0].duration_min == 10

    @pytest.mark.asyncio
    async def test_후보에_없는_place_id가_섞여도_편성을_막지_않는다(self) -> None:
        edges = await resolve_schedule_travel_edges(
            candidates=[_candidate("a", 127.0)],
            place_ids=["a", "unknown"],
            conditions=self._conditions,
            settings=Settings(),
            travel_route_tool=None,
        )
        # 그 구간만 빠지고 예외가 오르지 않는다.
        assert edges == ()

    @pytest.mark.asyncio
    async def test_실측이_통째로_실패해도_추정으로_낸다(self) -> None:
        class _Exploding:
            async def get_routes(self, *args, **kwargs):
                raise RuntimeError("boom")

        tool = _tool(_Exploding())
        edges = await resolve_schedule_travel_edges(
            candidates=[_candidate("a", 127.0), _candidate("b", 127.01)],
            place_ids=["a", "b"],
            conditions=self._conditions,
            settings=Settings(),
            travel_route_tool=tool,
        )
        assert len(edges) == 1
        assert edges[0].duration_min > 0
