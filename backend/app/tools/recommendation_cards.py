"""추천 카드 목록에 실을 장소 정보를 content_id 순서대로 조립하는 내부 Tool.

역할: A가 확정한 추천 순위(content_id 리스트)를 받아 카드가 표시할 썸네일·이름·
주차·카테고리·운영시간을 채운다. 순위 결정에는 관여하지 않는다 — 받은 순서를
그대로 유지해서 돌려준다.

**저장소가 돌려주는 행 순서를 믿지 않는다.** PostgREST의 `in.(...)`는 입력 순서를
보장하지 않아서, 조회 결과를 그대로 쓰면 A가 정한 순위가 조용히 뒤섞인다. 입력
순서로 다시 세운 뒤 반환한다.

조회되지 않은 content_id는 카드 목록에서 빠지되 `missing_content_ids`로 함께
돌려준다. 조용히 빼기만 하면 A가 기대한 개수와 어긋난 걸 알 방법이 없다.

외부 호출은 없다. 이미 동기화된 places 행만 읽으므로 카드 N건에 DB 조회 1회다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models import StoredPlaceDetail
from app.domain.operating_hours import OperatingSchedule, normalize_operating_schedule
from app.domain.parking import ParkingAvailability, normalize_parking
from app.errors import AppError
from app.providers.tour_category_registry import (
    TourCategoryRegistry,
    get_tour_category_registry,
)
from app.repositories.protocols import PlaceDetailsReadRepository
from app.tools.contracts import ToolError, ToolStatus


@dataclass(frozen=True)
class RecommendationCard:
    """추천 카드 1건이 표시할 정보."""

    content_id: str
    # places.title은 NOT NULL이고 공백도 제약으로 막혀 있어 실제로는 항상 값이 있다.
    # 저장소가 빈 문자열을 None으로 바꿔 주므로 타입만 옵셔널로 둔다.
    name: str | None
    # thumbnail_url(firstimage2)이 없으면 first_image_url(firstimage)로 대체한다.
    # 둘 다 없는 장소가 실측 844건 중 169건(20%)이라 None을 정상 값으로 다룬다.
    thumbnail_url: str | None
    # TourAPI 신분류 중분류명(예: 한식, 역사유적지, 전시시설).
    category_label: str | None
    parking_status: ParkingAvailability
    parking_note: str | None
    operating_schedule: OperatingSchedule


@dataclass(frozen=True)
class RecommendationCardResult:
    status: ToolStatus
    cards: tuple[RecommendationCard, ...]
    missing_content_ids: tuple[str, ...]
    error: ToolError | None = None


class RecommendationCardTool:
    """content_id 목록을 카드 표시 정보로 채운다."""

    def __init__(
        self,
        repository: PlaceDetailsReadRepository,
        registry: TourCategoryRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._registry = registry or get_tour_category_registry()

    async def get_cards(
        self, content_ids: Sequence[str]
    ) -> RecommendationCardResult:
        # 중복 id가 섞여도 조회는 한 번만 하고, 카드도 첫 등장 순서로 한 번만 낸다.
        ordered_ids = list(dict.fromkeys(content_ids))
        if not ordered_ids:
            return RecommendationCardResult(
                status=ToolStatus.NO_DATA,
                cards=(),
                missing_content_ids=(),
            )

        try:
            rows = await self._repository.get_active_place_details(ordered_ids)
        except AppError as exc:
            return RecommendationCardResult(
                status=ToolStatus.UNAVAILABLE,
                cards=(),
                missing_content_ids=tuple(ordered_ids),
                error=ToolError(
                    code="unavailable",
                    message="추천 카드 정보를 불러오지 못했습니다.",
                    cause="upstream_error",
                    retryable=exc.retryable,
                ),
            )

        cards = tuple(
            self._to_card(rows[content_id])
            for content_id in ordered_ids
            if content_id in rows
        )
        missing = tuple(
            content_id for content_id in ordered_ids if content_id not in rows
        )
        return RecommendationCardResult(
            status=_status(requested=len(ordered_ids), found=len(cards)),
            cards=cards,
            missing_content_ids=missing,
        )

    def _to_card(self, row: StoredPlaceDetail) -> RecommendationCard:
        parking = normalize_parking(row.parking_info_raw)
        return RecommendationCard(
            content_id=row.content_id,
            name=row.title,
            thumbnail_url=row.thumbnail_url or row.first_image_url,
            category_label=self._category_label(row),
            parking_status=parking.availability,
            parking_note=parking.note,
            # DB의 operating_schedule 컬럼이 아니라 원문을 다시 정규화한다 —
            # TourAPI를 직접 부르는 경로와 같은 함수를 써야 결과가 갈리지 않고,
            # 파서가 개선되면 재동기화 없이 반영된다(supabase_place_details.py와 동일).
            operating_schedule=normalize_operating_schedule(
                content_type_id=row.content_type_id,
                operating_hours=row.operating_hours_raw,
                rest_date=row.rest_date_raw,
            ),
        )

    def _category_label(self, row: StoredPlaceDetail) -> str | None:
        """중분류명을 카드 라벨로 쓴다.

        대분류(`쇼핑`, `음식`)는 카드에서 변별력이 없고 소분류(`사후면세점`,
        `관광식당`)는 지나치게 세분화돼 있어 중분류(`면세점`, `한식`)를 택했다.

        소분류 코드로 먼저 찾는다 — 실측 활성 844건의 소분류 코드 84종이 기준
        데이터에 모두 있어(2026-08-10 확인) 이 경로에서 전부 해석된다. 중분류
        코드 조회는 소분류가 비어 있는 행을 위한 대비책이다.
        """
        if row.lcls_systm3:
            category = self._registry.get_by_small_code(row.lcls_systm3)
            if category is not None:
                return category.lcls_systm2_name
        if row.lcls_systm2:
            matches = self._registry.find_by_middle_code(row.lcls_systm2)
            if matches:
                return matches[0].lcls_systm2_name
        return None


def _status(*, requested: int, found: int) -> ToolStatus:
    if found == 0:
        return ToolStatus.NO_DATA
    if found < requested:
        return ToolStatus.PARTIAL
    return ToolStatus.SUCCESS


__all__ = [
    "RecommendationCard",
    "RecommendationCardResult",
    "RecommendationCardTool",
]
