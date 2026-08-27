"""올린 사진과 분위기가 닮은 장소를 찾는 서비스.

역할: 위치 해석 → 주변 장소 조회 → 하드 필터 → 사진 유사도 순위.

`build_recommendations`(services/recommendations.py)와 앞부분이 같고 **마지막만
다르다.** 저쪽은 `score_prepared_recommendation()`으로 거리·취향·혼잡도를 섞어
점수를 내고, 이쪽은 그 단계를 건너뛰고 사진 유사도만으로 줄을 세운다.

  기존:  위치 → 장소 → prepare() → score_prepared()
  사진:  위치 → 장소 → prepare() → search_by_photo()

`prepare()`까지만 부르는 이유는 **하드 필터가 필요하기 때문이다.** 지금 닫힌
가게가 1등으로 나오면 쓸모가 없다. 채점은 필요 없지만 "갈 수 있는 곳인가"는
사진 경로에서도 똑같이 물어야 한다.

**날씨는 조회하지 않는다.** 날씨는 채점(실내외 선호)에만 쓰이고 하드 필터는
영업시간·이미 본 곳·거절한 곳만 본다. 후보 매핑도 `context.weather`를 읽지
않는다(recommendation_pipeline.py). 쓰지도 않을 외부 호출을 요청마다 하나
더 만들 이유가 없다.

**인텐트를 새로 만들지 않는다.** 인텐트는 "사용자 발화가 무엇을 원하는가"를
분류하는 장치인데, 사진은 발화가 아니라 이미 목적이 확정된 입력이다. 음성
전사(`/transcribe`)가 같은 이유로 인텐트 밖에 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.agent_context.mappers import map_location_context, map_places_context
from app.agent_context.schemas import RecommendationContext
from app.config import settings
from app.errors import AppError
from app.place_search_policy import DEFAULT_PLACE_SEARCH_RADIUS_KM
from app.providers.contracts import ProviderMetadata, ProviderSource, ProviderStatus
from app.providers.protocols import GeocodingProvider, PlaceProvider
from app.services.recommendation_pipeline import prepare_recommendation_from_context
from app.tools.contracts import ToolStatus
from app.tools.nearby_place_details import (
    NearbyPlaceDetailsQuery,
    NearbyPlaceDetailsTool,
)
from app.tools.resolve_location import (
    LocationPurpose,
    LocationSource,
    ResolutionConfidence,
    ResolutionMethod,
    ResolvedLocation,
    ResolveLocationQuery,
    ResolveLocationResult,
    ResolveLocationTool,
)

_KST = ZoneInfo("Asia/Seoul")

# search_place_mood RPC가 강제하는 후보 상한. 넘으면 저장소가 에러를 던지므로
# 여기서 앞에서부터 자른다. 후보는 거리순으로 와서 앞쪽이 더 가깝다.
_MAX_CANDIDATES = 500


@dataclass(frozen=True)
class PhotoSimilarQuery:
    """사진 검색 한 번의 입력.

    `location_query`가 있으면 그것으로 기준점을 풀고, 없으면 좌표를 그대로 쓴다.
    둘 다 없으면 어디서 찾을지 알 수 없어 `location_required`로 되묻는다 —
    기존 위치 되묻기와 같은 코드다(agent_context/assembler.py).
    """

    image_bytes: bytes
    location_query: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    search_radius_km: float | None = None
    limit: int = 10


@dataclass(frozen=True)
class PhotoSimilarPlaceRow:
    """사진 검색 결과 한 곳 — 유사도와 후보 정보를 합친 값.

    장소명·분류·거리는 `prepare()`가 돌려준 후보에서 그대로 가져온다. 상세를
    다시 조회하지 않는 이유는 그 값이 이미 손에 있기 때문이다 — 사진 검색이
    돌려주는 것은 content_id와 유사도뿐이라 이름을 붙이려면 어디선가 가져와야
    하는데, 후보 조회가 방금 그 일을 했다.
    """

    content_id: str
    name: str
    category: str
    distance_km: float
    similarity: float
    photo_count: int
    # 비교에 실제로 쓴 첫 사진. places.first_image_url과 다를 수 있다.
    image_url: str | None = None


@dataclass(frozen=True)
class PhotoSimilarResult:
    places: tuple[PhotoSimilarPlaceRow, ...]
    # 어디를 중심으로 찾았는지. 화면이 "내 주변에서 찾았어요"를 보여줄 때 쓴다.
    center_name: str
    center_latitude: float
    center_longitude: float
    # 하드 필터를 통과해 사진 검색에 넘어간 후보 수. 0이면 "닮은 곳이 없다"가
    # 아니라 "볼 곳 자체가 없었다"는 뜻이라 화면 문구가 달라져야 한다.
    candidate_count: int
    # 상한에 걸려 잘린 후보 수. 0이 아니면 반경을 좁히는 편이 낫다.
    truncated_count: int


async def build_photo_similar_places(
    query: PhotoSimilarQuery,
    *,
    geocoding_provider: GeocodingProvider,
    place_provider: PlaceProvider,
    mood_provider,
    place_repository=None,
    local_search_provider=None,
) -> PhotoSimilarResult:
    """위치 해석부터 사진 순위까지 한 번에 실행한다."""
    if not query.image_bytes:
        raise AppError(
            code="empty_image",
            message="사진이 비어 있어요. 다시 올려 주세요.",
            status_code=422,
            retryable=True,
        )
    if mood_provider is None or not mood_provider.photo_search_available:
        # 조용히 빈 결과를 주지 않는다. 기능이 꺼져 있는 것과 "닮은 곳이 없다"는
        # 다르고, 둘을 같은 응답으로 만들면 왜 안 나오는지 추적할 수 없다.
        raise AppError(
            code="photo_search_unavailable",
            message="사진으로 찾는 기능이 지금은 꺼져 있어요.",
            status_code=503,
            retryable=False,
        )

    center = await _resolve_center(
        query, geocoding_provider, place_repository, local_search_provider
    )
    # 반경을 안 주면 추천과 같은 기본값을 쓴다 — 사진 검색만 다른 범위를 보면
    # "추천에는 나왔는데 사진으로는 안 나온다"가 생긴다.
    radius_km = query.search_radius_km or DEFAULT_PLACE_SEARCH_RADIUS_KM
    visit_at = datetime.now(_KST)

    places_result = await NearbyPlaceDetailsTool(place_provider, place_provider).execute(
        NearbyPlaceDetailsQuery(
            latitude=center.latitude,
            longitude=center.longitude,
            search_radius_km=radius_km,
            limit=settings.recommendation_candidate_limit,
            preferred_categories=(),
            excluded_place_ids=frozenset(),
        )
    )

    context = RecommendationContext(
        location=map_location_context(center.result),
        places=map_places_context(places_result),
        # 날씨는 싣지 않는다 — 위 모듈 문서 참고.
    )
    prepared = await prepare_recommendation_from_context(context, visit_at=visit_at)
    place_ids = [
        item.candidate.place_id for item in prepared.preparation.eligible_candidates
    ]

    truncated = max(0, len(place_ids) - _MAX_CANDIDATES)
    if truncated:
        place_ids = place_ids[:_MAX_CANDIDATES]

    result = await mood_provider.search_by_photo(query.image_bytes, place_ids)

    # content_id → 후보. 사진 검색은 유사도만 주므로 이름을 여기서 붙인다.
    by_id = {
        item.candidate.place_id: item.candidate
        for item in prepared.preparation.eligible_candidates
    }
    # 보여줄 만큼만 조회한다. 후보 전체(최대 500)가 아니라 상위 N곳이면 된다.
    photo_urls = await mood_provider.first_photo_urls(
        [match.content_id for match in result.data[: query.limit]]
    )
    places = tuple(
        PhotoSimilarPlaceRow(
            content_id=match.content_id,
            name=candidate.name,
            category=candidate.category,
            distance_km=candidate.distance_km,
            similarity=match.similarity,
            photo_count=match.profile.photo_count,
            image_url=photo_urls.get(match.content_id),
        )
        for match in result.data[: query.limit]
        # 후보에 없는 content_id가 오면 건너뛴다. 후보를 좁혀 부르므로 정상적으로는
        # 일어나지 않지만, 조용히 이름 없는 카드를 내보내는 것보다 빠뜨리는 편이 낫다.
        if (candidate := by_id.get(match.content_id)) is not None
    )

    return PhotoSimilarResult(
        places=places,
        center_name=center.name,
        center_latitude=center.latitude,
        center_longitude=center.longitude,
        candidate_count=len(place_ids),
        truncated_count=truncated,
    )


@dataclass(frozen=True)
class _Center:
    result: object
    name: str
    latitude: float
    longitude: float


async def _resolve_center(
    query: PhotoSimilarQuery,
    geocoding_provider: GeocodingProvider,
    place_repository=None,
    local_search_provider=None,
) -> _Center:
    """기준점을 정한다. 지역명이 있으면 그것이 이긴다.

    사용자가 지역을 적었으면 GPS를 무시한다 — 명시한 쪽이 의도이고, 좌표는
    적지 않았을 때의 기본값이다(agent_context/service.py와 같은 우선순위).

    **저장소와 지역 검색을 함께 넘긴다.** 지오코딩만으로는 주소만 풀린다 —
    "안국역"처럼 장소명으로 말한 위치는 지역 검색이 담당하고, 저장된 장소는
    저장소가 먼저 답한다. 셋을 다 넘기지 않으면 채팅 경로에서는 되는 위치가
    사진 경로에서만 실패한다(2026-08-27에 실제로 그랬다).
    """
    if query.location_query:
        result = await ResolveLocationTool(
            geocoding_provider,
            place_repository=place_repository,
            local_search_provider=local_search_provider,
        ).execute(
            ResolveLocationQuery(
                query.location_query, purpose=LocationPurpose.SEARCH_CENTER
            )
        )
        if result.status is not ToolStatus.SUCCESS or result.location is None:
            raise AppError(
                code="location_required"
                if result.status is not ToolStatus.UNSUPPORTED
                else "unsupported_region",
                message="어디서 찾을지 알기 어려워요. 지역을 다시 알려 주세요.",
                status_code=422,
                retryable=True,
            )
        location = result.location
        return _Center(result, location.resolved_name, location.latitude, location.longitude)

    if query.latitude is None or query.longitude is None:
        raise AppError(
            code="location_required",
            message="어디서 찾을까요? 지역을 알려주시거나 위치를 켜 주세요.",
            status_code=422,
            retryable=True,
        )

    result = _gps_location_result(query.latitude, query.longitude)
    location = result.location
    assert location is not None  # 바로 위에서 만든 값이다
    return _Center(result, location.resolved_name, location.latitude, location.longitude)


def _gps_location_result(latitude: float, longitude: float) -> ResolveLocationResult:
    """기기 GPS 좌표를 위치 Tool 성공 결과로 정규화한다.

    지오코딩을 타지 않는다 — 좌표가 이미 확정된 값이라 풀 것이 없다.
    agent_context/service.py의 같은 이름 함수와 같은 모양이지만, 그쪽은
    `AgentContextRequest`를 받아 이 경로에서 쓸 수 없다.
    """
    return ResolveLocationResult(
        status=ToolStatus.SUCCESS,
        location=ResolvedLocation(
            requested_query="gps_location",
            provider_query="device_gps",
            resolved_name="기기 GPS 위치",
            source=LocationSource.DEVICE_GPS,
            latitude=latitude,
            longitude=longitude,
            resolution_method=ResolutionMethod.DIRECT,
            confidence=ResolutionConfidence.EXACT,
        ),
        error=None,
        provider_metadata=(
            ProviderMetadata(
                source=ProviderSource.DEVICE_GPS,
                status=ProviderStatus.SUCCESS,
                retrieved_at=datetime.now(UTC),
            ),
        ),
    )
