"""올린 사진과 분위기가 닮은 장소를 찾는 서비스.

역할: 위치 해석 → 사진 유사도 순위 → 상세 확인 → 하드 필터.

**순서가 추천과 반대다.** 추천은 후보를 먼저 모으고 점수를 내지만, 사진 검색은
먼저 줄을 세우고 상위 N곳만 상세를 확인한다.

  추천:   위치 → 장소 조회(상세 포함) → prepare() → score_prepared()
  사진:   위치 → 사진 순위(DB) → 상위 N곳 상세 → prepare()

**왜 뒤집었나.** 장소 조회는 후보마다 상세가 붙어 최대 20곳이다
(MAX_RECOMMENDATION_CANDIDATE_LIMIT). 2,009곳을 적재해 두고 20곳 안에서만
고르면 어떤 사진을 올려도 같은 대여섯 곳이 순서만 바뀐다. 사진 유사도는 DB
안에서 끝나 사실상 공짜이므로, 반경 안 전부를 먼저 줄 세우고 비싼 상세 조회를
"어차피 보여줄 곳"에만 쓴다.

**하드 필터 판정은 직접 하지 않는다.** `prepare_recommendation_from_context()`를
그대로 태운다 — 영업시간 해석을 여기서 새로 만들면 같은 장소가 추천에서는
열렸는데 사진 검색에서는 닫힌 것으로 갈릴 수 있다.

**날씨는 조회하지 않는다.** 날씨는 채점(실내외 선호)에만 쓰이고 하드 필터는
영업시간·이미 본 곳·거절한 곳만 본다. 후보 매핑도 `context.weather`를 읽지
않는다(recommendation_pipeline.py). 쓰지도 않을 외부 호출을 요청마다 하나
더 만들 이유가 없다.

**인텐트를 새로 만들지 않는다.** 인텐트는 "사용자 발화가 무엇을 원하는가"를
분류하는 장치인데, 사진은 발화가 아니라 이미 목적이 확정된 입력이다. 음성
전사(`/transcribe`)가 같은 이유로 인텐트 밖에 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.agent_context.mappers import map_location_context
from app.agent_context.schemas import (
    ContextValue,
    Coordinates,
    PlaceCandidate,
    RecommendationContext,
)
from app.errors import AppError
from app.place_search_policy import DEFAULT_PLACE_SEARCH_RADIUS_KM
from app.providers.contracts import ProviderMetadata, ProviderSource, ProviderStatus
from app.providers.place_mood_encoder import UnreadableImageError
from app.providers.protocols import GeocodingProvider, PlaceProvider
from app.services.recommendation_pipeline import prepare_recommendation_from_context
from app.tools.contracts import ToolStatus
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

# 보여줄 수보다 몇 배를 먼저 받을지. 상위 N곳 중 상당수가 영업시간에 걸려
# 빠지기 때문이다 — 실측에서 영업 중인 비율이 20곳 중 7곳(35%)이었다.
# 4배면 10곳을 채우는 데 40곳을 훑는 셈이고, 상세 조회는 DB라 값이 싸다.
_OVERFETCH_FACTOR = 4


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
    # True면 지금 닫힌 곳도 결과에 남긴다. "나중에 가볼 데"를 찾는 흐름을 위해
    # 열어 두지만 기본은 False다 — "이 분위기 어디 있어?"에 닫힌 가게가 1등으로
    # 나오면 쓸모가 없다.
    ignore_operating_hours: bool = False


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
    address: str | None = None
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
    details_repository,
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

    # ── 1단계: 반경 안 전부를 사진 유사도로 줄 세운다 ──────────────────
    # DB 안에서 끝나 사실상 공짜다. 보여줄 수보다 넉넉히 받는 이유는 다음
    # 단계에서 영업시간으로 걸러지기 때문이다 — 실측에서 영업 중인 비율이
    # 20곳 중 7곳(35%)이었다.
    try:
        ranked = await mood_provider.search_by_photo(
            query.image_bytes,
            None,
            latitude=center.latitude,
            longitude=center.longitude,
            radius_km=radius_km,
            match_count=query.limit * _OVERFETCH_FACTOR,
        )
    except UnreadableImageError as error:
        # 사용자 입력 문제다. 500으로 두면 서버 잘못이라는 뜻이 되어 로그와
        # 모니터링에서 진짜 장애와 섞이고, 화면도 "예상치 못한 오류"만 보여준다.
        raise AppError(
            code="unreadable_image",
            message="사진을 열 수 없어요. 다른 사진으로 올려 주세요.",
            status_code=422,
            retryable=True,
        ) from error
    if not ranked.data:
        return PhotoSimilarResult(
            places=(),
            center_name=center.name,
            center_latitude=center.latitude,
            center_longitude=center.longitude,
            candidate_count=0,
            truncated_count=0,
        )

    # ── 2단계: 상위 N곳만 상세를 확인한다 ─────────────────────────────
    # 비싼 조회를 "어차피 보여줄 곳"에만 쓴다. 순서를 뒤집기 전에는 후보를
    # 만들려고 상세를 먼저 다 조회해, 결과에 안 나갈 곳까지 값을 치렀다.
    top_ids = [match.content_id for match in ranked.data]
    details = await details_repository.get_active_place_details(top_ids)

    # ── 3단계: 하드 필터 ─────────────────────────────────────────────
    # **판정을 직접 하지 않는다.** prepare_recommendation_from_context()를 그대로
    # 태워 추천 경로와 같은 규칙을 쓴다 — 영업시간 해석을 여기서 새로 만들면
    # 같은 장소가 추천에서는 열렸는데 사진 검색에서는 닫힌 것으로 갈릴 수 있다.
    context = RecommendationContext(
        location=map_location_context(center.result),
        places=_places_context(ranked.data, details),
        # 날씨는 싣지 않는다 — 위 모듈 문서 참고.
    )
    prepared = await prepare_recommendation_from_context(
        context,
        visit_at=visit_at,
        ignore_operating_hours=query.ignore_operating_hours,
    )
    open_ids = {
        item.candidate.place_id for item in prepared.preparation.eligible_candidates
    }
    skipped_closed = len(top_ids) - len(open_ids)

    # ── 4단계: 사진 순위 그대로 상위 N곳만 남긴다 ─────────────────────
    # prepared는 후보를 다시 정렬하지 않지만, 순서를 ranked에서 가져와야 사진
    # 유사도 순서가 유지된다.
    rows: list[PhotoSimilarPlaceRow] = []
    for match in ranked.data:
        if match.content_id not in open_ids:
            continue
        detail = details.get(match.content_id)
        if detail is None:
            continue
        rows.append(
            PhotoSimilarPlaceRow(
                content_id=match.content_id,
                name=detail.title or match.content_id,
                category=detail.content_type_id,
                distance_km=match.distance_km or 0.0,
                similarity=match.similarity,
                photo_count=match.profile.photo_count,
                address=detail.address,
            )
        )
        if len(rows) >= query.limit:
            break

    # ── 5단계: 보여줄 것만 사진 주소를 붙인다 ─────────────────────────
    photo_urls = await mood_provider.first_photo_urls([row.content_id for row in rows])
    places = [replace(row, image_url=photo_urls.get(row.content_id)) for row in rows]

    return PhotoSimilarResult(
        places=tuple(places),
        center_name=center.name,
        center_latitude=center.latitude,
        center_longitude=center.longitude,
        # 사진으로 줄 세운 뒤 상세를 확인한 곳의 수. 0이면 반경 안에 사진 벡터가
        # 있는 장소 자체가 없었다는 뜻이다.
        candidate_count=len(ranked.data),
        # 영업시간에 걸려 빠진 수. 결과가 적을 때 왜인지 알 수 있어야 한다.
        truncated_count=skipped_closed,
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


def _places_context(matches, details):
    """사진 순위 결과를 하드 필터가 읽는 Context 모양으로 옮긴다.

    좌표는 싣지 않는다 — `prepare()`가 거리 점수를 내는 데 쓰지만 사진 검색은
    채점을 타지 않고, 순위는 이미 사진 유사도로 정해져 있다.
    """
    places = [
        PlaceCandidate(
            place_id=match.content_id,
            name=detail.title or match.content_id,
            category=detail.content_type_id,
            location=Coordinates(
                latitude=detail.latitude or 0.0,
                longitude=detail.longitude or 0.0,
            ),
            operating_hours_raw=detail.operating_hours_raw,
            rest_date_raw=detail.rest_date_raw,
        )
        for match in matches
        if (detail := details.get(match.content_id)) is not None
    ]
    return ContextValue(status="success", data=places or [])
