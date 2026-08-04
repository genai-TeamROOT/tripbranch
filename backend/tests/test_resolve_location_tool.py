from __future__ import annotations

from collections.abc import Iterable

import pytest

from app.domain.models import GeocodeResult, LocalSearchPlace, StoredPlaceLocation
from app.errors import AppError
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.tools.resolve_location import (
    ResolutionConfidence,
    ResolutionMethod,
    ResolveLocationQuery,
    ResolveLocationStatus,
    ResolveLocationTool,
    is_address_query,
    strip_location_modifiers,
)


class SequenceGeocodingProvider:
    def __init__(self, responses: Iterable[GeocodeResult | AppError]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[str, bool]] = []

    async def geocode(
        self, location_query: str, *, use_alias: bool = True
    ) -> ProviderResult[GeocodeResult]:
        self.calls.append((location_query, use_alias))
        response = next(self._responses)
        if isinstance(response, AppError):
            raise response
        return provider_result(response, source=ProviderSource.FAKE_GEOCODING)


def _result(
    *,
    query: str = "서울특별시 종로구 사직로 161",
    district: str | None = "종로구",
    count: int = 1,
) -> GeocodeResult:
    return GeocodeResult(
        query=query,
        resolved_name=query,
        latitude=37.5788,
        longitude=126.9770,
        candidate_count=count,
        administrative_district=district,
    )


class MemoryLocalSearchProvider:
    def __init__(self, places: tuple[LocalSearchPlace, ...]) -> None:
        self._places = places
        self.calls: list[str] = []

    async def search_places_by_name(
        self, query: str, *, display: int = 5
    ) -> ProviderResult[tuple[LocalSearchPlace, ...]]:
        self.calls.append(query)
        return provider_result(self._places, source=ProviderSource.FAKE_LOCAL_SEARCH)


class MemoryPlaceLocationRepository:
    def __init__(self, matches: tuple[StoredPlaceLocation, ...]) -> None:
        self._matches = matches
        self.calls: list[str] = []

    async def find_active_places_by_name(self, name: str) -> tuple[StoredPlaceLocation, ...]:
        self.calls.append(name)
        return self._matches


@pytest.mark.asyncio
async def test_resolves_stored_tour_place_before_geocoding() -> None:
    repository = MemoryPlaceLocationRepository(
        (
            StoredPlaceLocation(
                content_id="128553",
                title="쌈지길",
                address="서울특별시 종로구 인사동길 44",
                latitude=37.5743062352,
                longitude=126.9848674428,
                concentration_name="쌈지길",
            ),
        )
    )
    provider = SequenceGeocodingProvider([])

    result = await ResolveLocationTool(provider, repository).execute(ResolveLocationQuery("쌈지길"))

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolution_method is ResolutionMethod.DATABASE
    assert result.location.place_id == "128553"
    assert result.location.concentration_name == "쌈지길"
    assert result.provider_metadata[0].source is ProviderSource.SUPABASE_PLACES
    assert repository.calls == ["쌈지길"]
    assert provider.calls == []


@pytest.mark.asyncio
async def test_resolves_local_search_place_when_database_has_no_match() -> None:
    local_search = MemoryLocalSearchProvider(
        (
            LocalSearchPlace(
                name="쌈지길",
                address="서울특별시 종로구 관훈동 38",
                road_address="서울특별시 종로구 인사동길 44",
                category="쇼핑",
                latitude=37.5743062352,
                longitude=126.9848674428,
            ),
        )
    )
    provider = SequenceGeocodingProvider([])

    result = await ResolveLocationTool(
        provider,
        MemoryPlaceLocationRepository(()),
        local_search,
    ).execute(ResolveLocationQuery("쌈지길"))

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolution_method is ResolutionMethod.LOCAL_SEARCH
    assert result.location.address == "서울특별시 종로구 인사동길 44"
    assert result.warnings == ("local_search_used",)
    assert local_search.calls == ["쌈지길"]
    assert provider.calls == []


@pytest.mark.asyncio
async def test_local_search_result_outside_service_area_is_unsupported() -> None:
    """지원 지역 밖은 unsupported로 알린다(D-044).

    좌표만 얻고 지역을 확인하지 않으면 종로구로 고정된 장소 검색과 교집합이 0건이 되어
    "조건에 맞는 곳을 찾지 못했어요. 검색 범위를 넓혀볼까요?"가 나간다. 넓혀도 영영
    나오지 않는 안내라 사용자를 헛돌게 한다.
    """
    local_search = MemoryLocalSearchProvider(
        (
            LocalSearchPlace(
                name="망원역",
                address="서울특별시 마포구 망원동",
                road_address="서울특별시 마포구 월드컵로 137",
                category="지하철역",
                latitude=37.556068,
                longitude=126.9101053,
            ),
        )
    )
    provider = SequenceGeocodingProvider([])

    result = await ResolveLocationTool(
        provider,
        MemoryPlaceLocationRepository(()),
        local_search,
    ).execute(ResolveLocationQuery("망원역"))

    assert result.status is ResolveLocationStatus.UNSUPPORTED
    assert result.location is None
    assert result.error is not None
    assert result.error.code == "unsupported_region"
    assert result.error.cause == "outside_supported_region"
    # 지역 문제를 확인했으면 지오코딩까지 갈 이유가 없다.
    assert provider.calls == []


@pytest.mark.asyncio
async def test_ambiguous_local_search_outside_area_reports_region_not_clarification() -> None:
    """후보를 못 좁혔어도 전부 지역 밖이면 되묻지 않는다.

    "부산 해운대"에 "종로구 안에서 어느 장소인지 알려주세요"라고 되물으면 안 된다.
    """
    local_search = MemoryLocalSearchProvider(
        (
            LocalSearchPlace(
                name="해운대해수욕장",
                address="부산광역시 해운대구 우동",
                road_address=None,
                category="해수욕장",
                latitude=35.1587,
                longitude=129.1604,
            ),
            LocalSearchPlace(
                name="해운대시장",
                address="부산광역시 해운대구 중동",
                road_address=None,
                category="시장",
                latitude=35.1631,
                longitude=129.1633,
            ),
        )
    )

    result = await ResolveLocationTool(
        SequenceGeocodingProvider([]),
        MemoryPlaceLocationRepository(()),
        local_search,
    ).execute(ResolveLocationQuery("해운대"))

    assert result.status is ResolveLocationStatus.UNSUPPORTED
    assert result.error is not None
    assert result.error.cause == "outside_supported_region"


@pytest.mark.asyncio
async def test_place_name_uses_local_search_before_geocoding() -> None:
    local_search = MemoryLocalSearchProvider(
        (
            LocalSearchPlace(
                name="쌈지길",
                address="서울특별시 종로구 관훈동 38",
                road_address="서울특별시 종로구 인사동길 44",
                category="쇼핑",
                latitude=37.5743062352,
                longitude=126.9848674428,
            ),
        )
    )
    repository = MemoryPlaceLocationRepository(())
    geocoding = SequenceGeocodingProvider([])

    result = await ResolveLocationTool(geocoding, repository, local_search).execute(
        ResolveLocationQuery("쌈지길")
    )

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolution_method is ResolutionMethod.LOCAL_SEARCH
    assert repository.calls == ["쌈지길"]
    assert local_search.calls == ["쌈지길"]
    assert geocoding.calls == []


@pytest.mark.asyncio
async def test_address_uses_geocoding_without_place_name_lookups() -> None:
    repository = MemoryPlaceLocationRepository(())
    local_search = MemoryLocalSearchProvider(())
    geocoding = SequenceGeocodingProvider([_result(query="서울특별시 종로구 인사동길 44")])

    result = await ResolveLocationTool(geocoding, repository, local_search).execute(
        ResolveLocationQuery("서울특별시 종로구 인사동길 44")
    )

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolution_method is ResolutionMethod.DIRECT
    assert repository.calls == []
    assert local_search.calls == []
    assert geocoding.calls == [("서울특별시 종로구 인사동길 44", False)]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("쌈지길", False),
        ("서울특별시 종로구 인사동길 44", True),
        ("서울특별시 종로구 관훈동 38", True),
    ],
)
def test_detects_address_query_conservatively(query: str, expected: bool) -> None:
    assert is_address_query(query) is expected


@pytest.mark.asyncio
async def test_resolves_alias_in_jongno() -> None:
    provider = SequenceGeocodingProvider([_result()])
    tool = ResolveLocationTool(provider)

    result = await tool.execute(ResolveLocationQuery("경복궁"))

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolution_method is ResolutionMethod.ALIAS
    assert result.location.confidence is ResolutionConfidence.EXACT
    assert result.location.provider_query == "서울특별시 종로구 사직로 161"
    assert result.provider_metadata[0].source is ProviderSource.FAKE_GEOCODING
    assert provider.calls == [("서울특별시 종로구 사직로 161", False)]


@pytest.mark.asyncio
async def test_falls_back_to_original_only_after_alias_no_data() -> None:
    provider = SequenceGeocodingProvider(
        [
            AppError(code="location_not_found", message="없음", status_code=404),
            _result(query="서울특별시 종로구 경복궁"),
        ]
    )

    result = await ResolveLocationTool(provider).execute(ResolveLocationQuery("경복궁"))

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolution_method is ResolutionMethod.FALLBACK
    assert result.warnings == ("fallback_used",)
    assert len(result.provider_metadata) == 1
    assert provider.calls == [
        ("서울특별시 종로구 사직로 161", False),
        ("경복궁", False),
    ]


@pytest.mark.asyncio
async def test_does_not_fallback_after_provider_failure() -> None:
    provider = SequenceGeocodingProvider(
        [
            AppError(
                code="geocoding_unavailable",
                message="장애",
                status_code=502,
                retryable=True,
            )
        ]
    )

    result = await ResolveLocationTool(provider).execute(ResolveLocationQuery("경복궁"))

    assert result.status is ResolveLocationStatus.UNAVAILABLE
    assert result.error is not None
    assert result.error.code == "unavailable"
    assert result.error.retryable is True
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_resolves_search_center_outside_jongno_before_candidate_filtering() -> None:
    provider = SequenceGeocodingProvider(
        [_result(query="서울특별시 용산구 한강대로", district="용산구")]
    )

    result = await ResolveLocationTool(provider).execute(ResolveLocationQuery("서울역"))

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolved_name == "서울특별시 용산구 한강대로"
    assert result.provider_metadata[0].source is ProviderSource.FAKE_GEOCODING
    assert result.provider_metadata[0].status is ProviderStatus.SUCCESS
    assert result.provider_metadata[0].retrieved_at.tzinfo is not None


@pytest.mark.asyncio
async def test_ambiguous_location_requires_clarification() -> None:
    provider = SequenceGeocodingProvider([_result(count=3)])

    result = await ResolveLocationTool(provider).execute(ResolveLocationQuery("인사동"))

    assert result.status is ResolveLocationStatus.NO_DATA
    assert result.error is not None
    assert result.error.cause == "ambiguous_location"
    assert result.error.details["reason"] == "ambiguous_location"
    assert result.provider_metadata[0].source is ProviderSource.FAKE_GEOCODING
    assert result.provider_metadata[0].status is ProviderStatus.SUCCESS
    assert result.provider_metadata[0].retrieved_at.tzinfo is not None


@pytest.mark.asyncio
async def test_unknown_location_is_no_data() -> None:
    provider = SequenceGeocodingProvider(
        [AppError(code="location_not_found", message="없음", status_code=404)]
    )

    result = await ResolveLocationTool(provider).execute(ResolveLocationQuery("알 수 없는 장소"))

    assert result.status is ResolveLocationStatus.NO_DATA
    assert result.error is not None
    assert result.error.cause == "location_not_found"


@pytest.mark.parametrize("value", ["", " ", "가" * 201])
def test_validates_query(value: str) -> None:
    with pytest.raises(ValueError):
        ResolveLocationQuery(value)


def _local_place(
    name: str,
    *,
    category: str = "음식점>한식",
    latitude: float = 37.5743,
    longitude: float = 126.9848,
) -> LocalSearchPlace:
    return LocalSearchPlace(
        name=name,
        address="서울특별시 종로구 관훈동 38",
        road_address="서울특별시 종로구 인사동길 44",
        category=category,
        latitude=latitude,
        longitude=longitude,
    )


async def _resolve_with_local_search(
    places: tuple[LocalSearchPlace, ...], query: str
):
    local_search = MemoryLocalSearchProvider(places)
    geocoding = SequenceGeocodingProvider([])
    result = await ResolveLocationTool(
        geocoding, MemoryPlaceLocationRepository(()), local_search
    ).execute(ResolveLocationQuery(query))
    return result, geocoding


@pytest.mark.asyncio
async def test_local_search_selects_head_token_match_among_nearby_shops() -> None:
    """Local Search는 주변 상호까지 함께 준다. "안국역 3호선"만 역으로 인정한다.

    실측(2026-08-03): "안국역" 조회 시 역 1건 + 주변 음식점 4건이 반환됐다.
    """
    result, geocoding = await _resolve_with_local_search(
        (
            _local_place("안국역 3호선", category="교통,운수>지하철,전철"),
            _local_place("쿄와우동", category="음식점>일식>우동,소바"),
            _local_place("익선끝집", category="한식>육류,고기요리"),
        ),
        "안국역",
    )

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolved_name == "안국역 3호선"
    assert result.location.resolution_method is ResolutionMethod.LOCAL_SEARCH
    # 이름으로 확정했으므로 Geocoding fallback까지 가지 않는다.
    assert geocoding.calls == []


@pytest.mark.asyncio
async def test_local_search_does_not_pick_similar_prefix_name() -> None:
    """"안국역사거리"는 "안국역"과 다른 장소다 — startswith였다면 잘못 선택된다."""
    result, _ = await _resolve_with_local_search(
        (_local_place("안국역사거리"),), "안국역"
    )

    assert result.status is ResolveLocationStatus.NO_DATA
    assert result.error is not None
    assert result.error.cause == "ambiguous_location"


@pytest.mark.asyncio
async def test_local_search_groups_transit_candidates_of_one_station() -> None:
    """같은 역의 노선별 후보는 하나로 본다(D-045).

    지역 검색은 "종로3가역"에 1·3·5호선을 각각 돌려준다. 몇 호선인지 되물어도 카페를
    찾는 사용자에게는 답이 될 수 없고, 검색 반경이 2km라 어느 출입구를 골라도 결과가
    같다. 실측 최대 거리는 청량리역 381m다.
    """
    result, _ = await _resolve_with_local_search(
        (
            _local_place(
                "종로3가역 3호선",
                category="교통,운수>지하철,전철",
                latitude=37.5714,
                longitude=126.9920,
            ),
            _local_place(
                "종로3가역 1호선",
                category="교통,운수>지하철,전철",
                latitude=37.5703,
                longitude=126.9918,
            ),
            _local_place(
                "종로3가역 5호선",
                category="교통,운수>지하철,전철",
                latitude=37.5710,
                longitude=126.9945,
            ),
        ),
        "종로3가역",
    )

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolved_name == "종로3가역 3호선"


@pytest.mark.asyncio
async def test_local_search_asks_again_when_transit_candidates_are_far_apart() -> None:
    """교통 시설이어도 멀리 떨어져 있으면 같은 역이 아니다."""
    result, _ = await _resolve_with_local_search(
        (
            _local_place(
                "OO역 3호선",
                category="교통,운수>지하철,전철",
                latitude=37.5743,
                longitude=126.9848,
            ),
            _local_place(
                "OO역 1호선",
                category="교통,운수>지하철,전철",
                latitude=37.5900,
                longitude=126.9848,
            ),
        ),
        "OO역",
    )

    assert result.status is ResolveLocationStatus.NO_DATA
    assert result.error is not None
    assert result.error.cause == "ambiguous_location"


@pytest.mark.asyncio
async def test_local_search_does_not_group_when_a_shop_shares_the_name() -> None:
    """상호가 하나라도 섞이면 묶지 않는다.

    거리만 보면 "종각역 김밥천국"처럼 역명을 그대로 앞에 붙인 상호가 함께 묶여, 첫
    후보를 임의로 고르지 않는다는 원칙이 깨진다.
    """
    result, _ = await _resolve_with_local_search(
        (
            _local_place("종각역 1호선", category="교통,운수>지하철,전철"),
            _local_place("종각역 김밥천국", category="음식점>한식"),
        ),
        "종각역",
    )

    assert result.status is ResolveLocationStatus.NO_DATA
    assert result.error is not None
    assert result.error.cause == "ambiguous_location"


@pytest.mark.asyncio
async def test_local_search_asks_again_when_exact_name_duplicated() -> None:
    """정확 일치가 여러 건이면 첫 토큰으로도 못 좁히므로 바로 재질문한다."""
    result, _ = await _resolve_with_local_search(
        (_local_place("쌈지길"), _local_place("쌈지길")), "쌈지길"
    )

    assert result.status is ResolveLocationStatus.NO_DATA
    assert result.error is not None
    assert result.error.cause == "ambiguous_location"


@pytest.mark.asyncio
async def test_local_search_prefers_exact_match_over_head_token() -> None:
    """정확 일치가 있으면 첫 토큰 단계로 내려가지 않는다."""
    result, _ = await _resolve_with_local_search(
        (_local_place("안국역 3호선"), _local_place("안국역")), "안국역"
    )

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolved_name == "안국역"


@pytest.mark.asyncio
async def test_local_search_without_candidates_falls_back_to_geocoding() -> None:
    """후보가 아예 없는 것과 좁히지 못한 것은 다르다.

    없으면 Geocoding이 받아야 하고(행정동 등), 있는데 못 좁혔으면 재질문한다.
    """
    local_search = MemoryLocalSearchProvider(())
    geocoding = SequenceGeocodingProvider([_result(query="청운효자동")])

    result = await ResolveLocationTool(
        geocoding, MemoryPlaceLocationRepository(()), local_search
    ).execute(ResolveLocationQuery("청운효자동"))

    assert result.status is ResolveLocationStatus.SUCCESS
    assert local_search.calls == ["청운효자동"]
    assert geocoding.calls != []


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("안국역 근처", "안국역"),
        ("경복궁 주변", "경복궁"),
        ("쌈지길 인근", "쌈지길"),
        ("서울역 부근", "서울역"),
        # 수식어만 있는 입력은 잘라낼 게 없어 원문을 유지한다.
        ("근처", "근처"),
        # 이름에 붙어 있으면 건드리지 않는다.
        ("역근처식당", "역근처식당"),
        ("근처식당 근처", "근처식당"),
    ],
)
def test_strip_location_modifiers(query: str, expected: str) -> None:
    assert strip_location_modifiers(query) == expected


@pytest.mark.asyncio
async def test_place_name_lookup_ignores_trailing_modifier() -> None:
    """A가 "안국역 근처"로 넘겨도 "안국역"으로 조회한다.

    실측(2026-08-03): "안국역 근처"로 지역 검색하면 엘리베이터·모텔·돈까스집이
    나와 정답인 "안국역 3호선"이 후보에 없었다.
    """
    local_search = MemoryLocalSearchProvider((_local_place("안국역 3호선"),))
    geocoding = SequenceGeocodingProvider([])

    result = await ResolveLocationTool(
        geocoding, MemoryPlaceLocationRepository(()), local_search
    ).execute(ResolveLocationQuery("안국역 근처"))

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolved_name == "안국역 3호선"
    # Provider에는 수식어를 뺀 값이 전달된다.
    assert local_search.calls == ["안국역"]


@pytest.mark.asyncio
async def test_address_with_modifier_is_still_treated_as_address() -> None:
    """"인사동길 44 근처"처럼 수식어가 붙은 주소도 Geocoding으로 보낸다."""
    local_search = MemoryLocalSearchProvider(())
    geocoding = SequenceGeocodingProvider([_result(query="서울특별시 종로구 인사동길 44")])

    result = await ResolveLocationTool(
        geocoding, MemoryPlaceLocationRepository(()), local_search
    ).execute(ResolveLocationQuery("서울특별시 종로구 인사동길 44 근처"))

    assert result.status is ResolveLocationStatus.SUCCESS
    assert local_search.calls == []
    assert geocoding.calls == [("서울특별시 종로구 인사동길 44", False)]
