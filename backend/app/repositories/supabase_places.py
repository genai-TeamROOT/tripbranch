"""Supabase PostgREST를 사용하는 장소 동기화 저장소."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TypeVar
from uuid import UUID

import httpx

from app.domain.models import (
    PlaceEvidenceMatch,
    PlaceEvidenceSnippet,
    StoredPlaceDetail,
    StoredPlaceLocation,
    StoredPlaceState,
    TourPlaceRecord,
)
from app.errors import AppError
from app.place_search_policy import (
    PLACE_SEARCH_LDONG_DISTRICT_CODE,
    PLACE_SEARCH_LDONG_REGION_CODE,
)

# search_place_evidence RPC가 강제하는 후보 상한. 넘으면 RPC가 즉시 에러를
# 던진다 — 여기서 미리 막아 왕복 한 번을 아끼고, 실패 지점을 호출부 가까이 둔다.
_MAX_EVIDENCE_CANDIDATES = 500

_READ_PAGE_SIZE = 1000
_UPSERT_CHUNK_SIZE = 100
_PLACE_SUMMARY_COLUMNS = ",".join(
    (
        "area_code",
        "district_code",
        "is_active",
        "detail_fetch_status",
        "operating_parse_status",
        "operating_parser_version",
        "detail_fetched_at",
    )
)
_STATE_COLUMNS = ",".join(
    (
        "content_id",
        "source_modified_at",
        "detail_fetched_at",
        "detail_fetch_status",
        "operating_parser_version",
        "operating_hours_raw",
        "rest_date_raw",
        "is_active",
        "inactive_reason",
    )
)
_LOCATION_COLUMNS = (
    "content_id,title,address,latitude,longitude,"
    "place_concentration_mappings(primary_concentration_name,concentration_search_keys)"
)

# 별칭 조회는 매핑이 있는 장소로만 좁혀야 해서 inner join이 필요하다.
_LOCATION_COLUMNS_INNER = _LOCATION_COLUMNS.replace(
    "place_concentration_mappings(", "place_concentration_mappings!inner("
)

_DETAIL_COLUMNS = ",".join(
    (
        "content_id",
        "content_type_id",
        "title",
        "address",
        # COMPARE TRAVEL_TIME 실측 연결(2026-08-21)이 쓴다.
        "latitude",
        "longitude",
        "operating_hours_raw",
        "rest_date_raw",
        "detail_fetch_status",
        "detail_fetched_at",
        "source_modified_at",
        # 추천 카드용 컬럼(D-056). 분류 코드는 카테고리 라벨, 주차·이미지는 배지와
        # 썸네일에 쓴다. 상세 배치 조회는 이미 장소당 1행이라 컬럼을 늘려도
        # 요청 수는 그대로다.
        "lcls_systm1",
        "lcls_systm2",
        "lcls_systm3",
        "parking_info_raw",
        "parking_fee_raw",
        "first_image_url",
        "thumbnail_url",
        # INFO 상세 질의(요금·전화번호)를 캐시만으로 답하기 위한 컬럼.
        "use_fee_raw",
        "info_center_raw",
        "baby_carriage_raw",
        "pet_raw",
        "credit_card_raw",
        "restroom_raw",
    )
)
_VALID_RUN_STATUSES = {"success", "partial_failure", "failed"}
_VALID_PARSE_STATUSES = {"parsed", "partial", "unknown", "assumed"}
T = TypeVar("T")


class SupabaseRepositoryError(AppError):
    """Supabase 요청이나 응답이 저장소 계약을 만족하지 못한 경우."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            code="supabase_repository_error",
            message="장소 데이터 저장 중 문제가 발생했어요.",
            status_code=502,
            retryable=True,
            provider="supabase",
            details={"upstream_detail": detail},
        )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: object, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise SupabaseRepositoryError(f"invalid {field}") from None


def _map_place_locations(
    rows: list[object], *, fallback_title: str
) -> tuple[StoredPlaceLocation, ...]:
    """places 조회 행을 StoredPlaceLocation으로 옮긴다. 좌표 없는 행은 버린다."""
    locations: list[StoredPlaceLocation] = []
    for raw in rows:
        if not isinstance(raw, Mapping) or not raw.get("content_id"):
            raise SupabaseRepositoryError("place location missing content_id")
        try:
            latitude = float(raw["latitude"])
            longitude = float(raw["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        # places ↔ place_concentration_mappings는 1:1(FK가 PK)이라 PostgREST가 단일
        # 객체로 내려준다. 관계 형태가 바뀌어 배열로 올 경우도 함께 받는다.
        mapping = raw.get("place_concentration_mappings")
        if isinstance(mapping, list):
            mapping = mapping[0] if mapping else None
        concentration_name = (
            _optional_text(mapping.get("primary_concentration_name"))
            if isinstance(mapping, Mapping)
            else None
        )
        # tAtsNm은 공백이 든 값에 0건을 돌려주므로 조회용 검색어를 따로 둔다.
        # 목록으로 받아 앞에서부터 시도한다(D-057).
        concentration_search_keys = _search_keys(
            mapping.get("concentration_search_keys") if isinstance(mapping, Mapping) else None
        )
        locations.append(
            StoredPlaceLocation(
                content_id=str(raw["content_id"]),
                title=str(raw.get("title") or fallback_title),
                address=_optional_text(raw.get("address")),
                latitude=latitude,
                longitude=longitude,
                concentration_name=concentration_name,
                concentration_search_keys=concentration_search_keys,
            )
        )
    return tuple(locations)


def _title_filters(name: str) -> list[str]:
    """장소명 조회에 쓸 PostgREST 필터를 좁은 것부터 나열한다.

    부분 일치로 넓히지 않는다 - "종묘*"로 찾으면 종묘광장공원·종묘대제까지 걸려
    엉뚱한 장소가 검색 중심이 된다. 이름 뒤에 괄호 부기만 붙은 형태로 한정한다.
    PostgREST는 ilike의 `*`를 `%`로 바꿔 주므로 인코딩 문제가 없다.
    """
    filters = [f"eq.{name}"]
    if any(character.isspace() for character in name):
        # "북촌 한옥마을" → "북촌한옥마을"
        filters.append("ilike." + "*".join(name.split()))
    # "종묘" → "종묘 [유네스코 세계유산]", "세검정 터" → "세검정 터 (구 세검정)"
    filters.extend([f"ilike.{name} [*", f"ilike.{name} (*"])
    return filters


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _search_keys(value: object) -> tuple[str, ...]:
    """집중률 검색어 목록을 순서 그대로 읽는다(D-057).

    공백이 든 값은 tAtsNm에 넣으면 무엇을 넣든 0건이 돌아오므로 여기서 버린다.
    DB 제약이 같은 것을 막고 있지만, 저장소를 거치지 않고 들어온 값이나 제약이
    없던 시절의 행이 조용히 0건 조회를 만들지 않도록 읽는 쪽에서도 막는다.
    """
    if not isinstance(value, list):
        return ()
    keys: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text and not any(character.isspace() for character in text):
            keys.append(text)
    return tuple(keys)


def _chunks(values: Sequence[T], size: int) -> list[Sequence[T]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


class SupabasePlaceRepository:
    def __init__(
        self,
        supabase_url: str,
        secret_key: str,
        client: httpx.AsyncClient,
        timeout_seconds: float = 10.0,
    ) -> None:
        normalized_url = supabase_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("supabase_url이 필요합니다.")
        if not secret_key.strip():
            raise ValueError("secret_key가 필요합니다.")
        self._rest_url = f"{normalized_url}/rest/v1"
        self._secret_key = secret_key
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self._secret_key,
            "Content-Type": "application/json",
        }
        if prefer is not None:
            headers["Prefer"] = prefer
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: object | None = None,
        prefer: str | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                self._rest_url + path,
                params=params,
                json=json,
                headers=self._headers(prefer),
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            return response
        except httpx.TimeoutException:
            response = None
            raise SupabaseRepositoryError("request timeout") from None
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            detail = f"HTTP {status_code}"
            try:
                error_payload = exc.response.json()
                if isinstance(error_payload, Mapping):
                    code = str(error_payload.get("code", "")).strip()
                    message = str(error_payload.get("message", "")).strip()
                    safe_parts = [part for part in (code, message) if part]
                    if safe_parts:
                        detail = f"{detail}: {' - '.join(safe_parts)}"
            except ValueError:
                pass
            response = None
            exc = None
            raise SupabaseRepositoryError(detail) from None
        except httpx.HTTPError:
            response = None
            raise SupabaseRepositoryError("request failed") from None

    @staticmethod
    def _json(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError:
            raise SupabaseRepositoryError("non-JSON response") from None

    async def search_place_evidence(
        self,
        query_embedding: Sequence[float],
        candidate_content_ids: Sequence[str],
        *,
        match_count: int,
        min_similarity: float,
    ) -> tuple[PlaceEvidenceMatch, ...]:
        """취향 질의 임베딩으로 후보 범위 안에서만 근거 문장을 찾는다.

        후보를 좁히지 않으면 RPC가 전체 행을 훑어 수 초가 걸리므로(2026-08-18
        실측: 200~400건 100~300ms, 844건 6~9초) 상한을 여기서 먼저 막는다.
        """
        unique_ids = list(dict.fromkeys(candidate_content_ids))
        if not unique_ids:
            return ()
        if len(unique_ids) > _MAX_EVIDENCE_CANDIDATES:
            raise SupabaseRepositoryError(
                f"후보 content_id가 {len(unique_ids)}건입니다. "
                f"{_MAX_EVIDENCE_CANDIDATES}건 이하로 좁혀서 호출하세요."
            )

        response = await self._request(
            "POST",
            "/rpc/search_place_evidence",
            json={
                "p_query_embedding": list(query_embedding),
                "p_candidate_content_ids": unique_ids,
                "p_match_count": match_count,
                "p_min_similarity": min_similarity,
            },
        )
        payload = self._json(response)
        if not isinstance(payload, list):
            raise SupabaseRepositoryError("invalid search_place_evidence response")
        return tuple(_to_evidence_match(row) for row in payload)


    async def create_sync_run(self, area_code: str, district_code: str) -> UUID:
        response = await self._request(
            "POST",
            "/place_sync_runs",
            json={"area_code": area_code, "district_code": district_code},
            prefer="return=representation",
        )
        payload = self._json(response)
        if not isinstance(payload, list) or len(payload) != 1:
            raise SupabaseRepositoryError("invalid sync run insert response")
        row = payload[0]
        if not isinstance(row, Mapping) or not row.get("id"):
            raise SupabaseRepositoryError("sync run response missing id")
        try:
            return UUID(str(row["id"]))
        except ValueError:
            raise SupabaseRepositoryError("invalid sync run id") from None

    async def try_acquire_sync_lock(
        self,
        area_code: str,
        district_code: str,
        sync_run_id: UUID,
        lock_ttl: str = "2 hours",
    ) -> bool:
        response = await self._request(
            "POST",
            "/rpc/try_acquire_place_sync_lock",
            json={
                "p_area_code": area_code,
                "p_district_code": district_code,
                "p_sync_run_id": str(sync_run_id),
                "p_lock_ttl": lock_ttl,
            },
        )
        payload = self._json(response)
        if not isinstance(payload, bool):
            raise SupabaseRepositoryError("invalid acquire lock response")
        return payload

    async def release_sync_lock(
        self,
        area_code: str,
        district_code: str,
        sync_run_id: UUID,
    ) -> bool:
        response = await self._request(
            "POST",
            "/rpc/release_place_sync_lock",
            json={
                "p_area_code": area_code,
                "p_district_code": district_code,
                "p_sync_run_id": str(sync_run_id),
            },
        )
        payload = self._json(response)
        if not isinstance(payload, bool):
            raise SupabaseRepositoryError("invalid release lock response")
        return payload

    async def get_region_place_states(
        self,
        area_code: str,
        district_code: str,
    ) -> dict[str, StoredPlaceState]:
        rows: list[object] = []
        offset = 0
        while True:
            response = await self._request(
                "GET",
                "/places",
                params={
                    "select": _STATE_COLUMNS,
                    "area_code": f"eq.{area_code}",
                    "district_code": f"eq.{district_code}",
                    "order": "content_id.asc",
                    "limit": str(_READ_PAGE_SIZE),
                    "offset": str(offset),
                },
            )
            page = self._json(response)
            if not isinstance(page, list):
                raise SupabaseRepositoryError("invalid place states response")
            rows.extend(page)
            if len(page) < _READ_PAGE_SIZE:
                break
            offset += _READ_PAGE_SIZE

        states: dict[str, StoredPlaceState] = {}
        for raw in rows:
            if not isinstance(raw, Mapping) or not raw.get("content_id"):
                raise SupabaseRepositoryError("place state missing content_id")
            content_id = str(raw["content_id"])
            states[content_id] = StoredPlaceState(
                content_id=content_id,
                source_modified_at=_parse_datetime(
                    raw.get("source_modified_at"), "source_modified_at"
                ),
                detail_fetched_at=_parse_datetime(
                    raw.get("detail_fetched_at"), "detail_fetched_at"
                ),
                detail_fetch_status=str(raw.get("detail_fetch_status", "")),
                operating_parser_version=str(raw.get("operating_parser_version", "")),
                operating_hours_raw=(
                    str(raw["operating_hours_raw"])
                    if raw.get("operating_hours_raw") is not None
                    else None
                ),
                rest_date_raw=(
                    str(raw["rest_date_raw"])
                    if raw.get("rest_date_raw") is not None
                    else None
                ),
                is_active=bool(raw.get("is_active")),
                inactive_reason=(
                    str(raw["inactive_reason"])
                    if raw.get("inactive_reason") is not None
                    else None
                ),
            )
        return states

    async def find_active_places_by_name(
        self, name: str
    ) -> tuple[StoredPlaceLocation, ...]:
        """TourAPI 기준 장소명을 정확히 일치시켜 검색 중심 좌표를 읽는다.

        장소명 검색은 지오코딩보다 먼저 수행한다. 좌표가 없는 행은 검색 중심점으로
        사용할 수 없으므로 반환하지 않는다. 별칭·부분 일치 정책은 상위 Tool이
        별도 경로로 확장할 수 있도록 이 Repository는 정확 일치만 담당한다.

        다만 공백 유무와 괄호 부기는 표기 차이로 본다. 지역 검색은 "북촌 한옥마을"을
        주는데 저장소에는 "북촌한옥마을"로 들어 있고, 사용자는 "종묘"라고 하는데
        저장소 제목은 "종묘 [유네스코 세계유산]"이다. 정확 일치만 보면 모두 놓친다.
        """
        normalized_name = name.strip()
        if not normalized_name:
            return ()
        for title_filter in _title_filters(normalized_name):
            rows = await self._query_places_by_title(title_filter)
            if rows:
                return _map_place_locations(rows, fallback_title=normalized_name)
        # 제목으로 못 찾으면 사람이 지정한 별칭을 본다. "창덕궁"은 저장소 제목이
        # "창덕궁과 후원 [유네스코 세계유산]"이라 어떤 제목 규칙으로도 닿지 않는다.
        rows = await self._query_places_by_alias(normalized_name)
        return _map_place_locations(rows, fallback_title=normalized_name)

    async def _query_places_by_alias(self, alias: str) -> list[object]:
        """매핑 별칭으로 장소를 찾는다. 별칭이 없는 장소는 조인에서 빠진다.

        지원 지역(area_code/district_code)을 명시적으로 걸어둔다. 이 메서드가
        읽는 결과는 호출자(resolve_location)가 지역 경계 검사를 건너뛰는
        경로라(D-044, "저장소에서 해석된 장소는 이미 종로구로 등록된 것") —
        places 테이블에 다른 구 데이터가 들어오는 순간 그 전제가 깨진다.
        RAG 실험 등으로 다른 구 장소가 이 테이블에 섞여도 실제 서비스 동작이
        조용히 바뀌지 않도록 여기서 필터로 막아둔다.
        """
        response = await self._request(
            "GET",
            "/places",
            params={
                "select": _LOCATION_COLUMNS_INNER,
                "is_active": "eq.true",
                "area_code": f"eq.{PLACE_SEARCH_LDONG_REGION_CODE}",
                "district_code": f"eq.{PLACE_SEARCH_LDONG_DISTRICT_CODE}",
                "place_concentration_mappings.concentration_aliases": f"cs.{{{alias}}}",
                "limit": "2",
            },
        )
        rows = self._json(response)
        if not isinstance(rows, list):
            raise SupabaseRepositoryError("invalid place location response")
        return rows

    async def _query_places_by_title(self, title_filter: str) -> list[object]:
        # _query_places_by_alias와 같은 이유로 지원 지역을 명시적으로 건다.
        response = await self._request(
            "GET",
            "/places",
            params={
                "select": _LOCATION_COLUMNS,
                "title": title_filter,
                "is_active": "eq.true",
                "area_code": f"eq.{PLACE_SEARCH_LDONG_REGION_CODE}",
                "district_code": f"eq.{PLACE_SEARCH_LDONG_DISTRICT_CODE}",
                "limit": "2",
            },
        )
        rows = self._json(response)
        if not isinstance(rows, list):
            raise SupabaseRepositoryError("invalid place location response")
        return rows

    async def find_concentration_mapped_places(self) -> tuple[StoredPlaceLocation, ...]:
        """집중률 매핑이 있는 활성 장소를 좌표와 함께 모두 읽는다.

        매핑에 있는 장소는 집중률 API에 데이터가 존재한다는 뜻이다. INFO 질의에서
        대상 장소의 직접 데이터가 없을 때, 여기서 가장 가까운 곳을 대체 기준으로
        쓰면 "가까운 곳을 골랐는데 집중률이 없더라"를 구조적으로 피할 수 있다.
        PostgREST가 거리 정렬을 지원하지 않아 전체를 읽고 호출자가 계산한다 —
        매핑은 100건 규모라 한 번에 받아도 부담이 없다.
        """
        response = await self._request(
            "GET",
            "/places",
            params={
                "select": _LOCATION_COLUMNS,
                "is_active": "eq.true",
                # 내부 조인으로 매핑이 있는 장소만 남긴다.
                "place_concentration_mappings": "not.is.null",
                "limit": str(_READ_PAGE_SIZE),
            },
        )
        rows = self._json(response)
        if not isinstance(rows, list):
            raise SupabaseRepositoryError("invalid concentration mapping response")
        return tuple(
            location
            for location in _map_place_locations(rows, fallback_title="")
            if location.concentration_name
        )

    async def get_active_place_details(
        self,
        content_ids: Sequence[str],
    ) -> dict[str, StoredPlaceDetail]:
        """활성 상태인 장소들의 상세·운영정보를 content_id 기준으로 한 번에 읽는다.

        조회되지 않은 content_id는 결과에 포함되지 않는다. content_id가 URL 길이
        제한을 넘지 않도록 청크로 나눠 요청한다.
        """
        if not content_ids:
            return {}

        details: dict[str, StoredPlaceDetail] = {}
        for chunk in _chunks(list(content_ids), _UPSERT_CHUNK_SIZE):
            quoted_ids = ",".join(f'"{content_id}"' for content_id in chunk)
            response = await self._request(
                "GET",
                "/places",
                params={
                    "select": _DETAIL_COLUMNS,
                    "content_id": f"in.({quoted_ids})",
                    "is_active": "eq.true",
                },
            )
            rows = self._json(response)
            if not isinstance(rows, list):
                raise SupabaseRepositoryError("invalid place details response")
            for raw in rows:
                if not isinstance(raw, Mapping) or not raw.get("content_id"):
                    raise SupabaseRepositoryError("place detail missing content_id")
                content_id = str(raw["content_id"])
                details[content_id] = StoredPlaceDetail(
                    content_id=content_id,
                    content_type_id=str(raw.get("content_type_id") or ""),
                    title=_optional_text(raw.get("title")),
                    address=_optional_text(raw.get("address")),
                    latitude=_optional_float(raw.get("latitude")),
                    longitude=_optional_float(raw.get("longitude")),
                    operating_hours_raw=_optional_text(raw.get("operating_hours_raw")),
                    rest_date_raw=_optional_text(raw.get("rest_date_raw")),
                    detail_fetch_status=str(raw.get("detail_fetch_status") or ""),
                    detail_fetched_at=_parse_datetime(
                        raw.get("detail_fetched_at"), "detail_fetched_at"
                    ),
                    source_modified_at=_parse_datetime(
                        raw.get("source_modified_at"), "source_modified_at"
                    ),
                    lcls_systm1=_optional_text(raw.get("lcls_systm1")),
                    lcls_systm2=_optional_text(raw.get("lcls_systm2")),
                    lcls_systm3=_optional_text(raw.get("lcls_systm3")),
                    parking_info_raw=_optional_text(raw.get("parking_info_raw")),
                    parking_fee_raw=_optional_text(raw.get("parking_fee_raw")),
                    first_image_url=_optional_text(raw.get("first_image_url")),
                    thumbnail_url=_optional_text(raw.get("thumbnail_url")),
                    use_fee_raw=_optional_text(raw.get("use_fee_raw")),
                    info_center_raw=_optional_text(raw.get("info_center_raw")),
                    baby_carriage_raw=_optional_text(raw.get("baby_carriage_raw")),
                    pet_raw=_optional_text(raw.get("pet_raw")),
                    credit_card_raw=_optional_text(raw.get("credit_card_raw")),
                    restroom_raw=_optional_text(raw.get("restroom_raw")),
                )
        return details

    async def upsert_place_list(
        self,
        places: Sequence[TourPlaceRecord],
        existing_states: Mapping[str, StoredPlaceState],
        sync_run_id: UUID,
        fetched_at: datetime,
    ) -> None:
        fetched_at_text = _iso(fetched_at)
        payloads: list[dict[str, object]] = []
        for place in places:
            row: dict[str, object] = {
                "content_id": place.content_id,
                "content_type_id": place.content_type_id,
                "title": place.title,
                "address": place.address,
                "latitude": place.latitude,
                "longitude": place.longitude,
                "area_code": place.area_code,
                "district_code": place.district_code,
                "lcls_systm1": place.lcls_systm1,
                "lcls_systm2": place.lcls_systm2,
                "lcls_systm3": place.lcls_systm3,
                "source_modified_at": _iso(place.source_modified_at),
                # 이미지는 목록 응답에서 오므로 상세조회 성패와 무관하게 갱신된다(D-056).
                "first_image_url": place.first_image_url,
                "thumbnail_url": place.thumbnail_url,
                "list_fetched_at": fetched_at_text,
                "last_seen_at": fetched_at_text,
                "last_sync_run_id": str(sync_run_id),
            }
            previous = existing_states.get(place.content_id)
            if previous is None:
                row.update({"detail_fetch_status": "pending", "is_active": True})
            elif previous.inactive_reason == "missing_from_source":
                row.update(
                    {
                        "is_active": True,
                        "inactive_reason": None,
                        "inactive_at": None,
                    }
                )
            payloads.append(row)

        payload_groups: dict[tuple[str, ...], list[dict[str, object]]] = {}
        for payload in payloads:
            key_shape = tuple(sorted(payload))
            payload_groups.setdefault(key_shape, []).append(payload)

        for group in payload_groups.values():
            for chunk in _chunks(group, _UPSERT_CHUNK_SIZE):
                await self._request(
                    "POST",
                    "/places",
                    params={"on_conflict": "content_id"},
                    json=list(chunk),
                    prefer="resolution=merge-duplicates,return=minimal",
                )

    async def update_operating_details(
        self,
        content_id: str,
        operating_hours_raw: str | None,
        rest_date_raw: str | None,
        operating_schedule: Mapping[str, object] | None,
        parse_status: str,
        parser_version: str,
        fetched_at: datetime,
        parking_info_raw: str | None = None,
        parking_fee_raw: str | None = None,
        use_fee_raw: str | None = None,
        discount_info_raw: str | None = None,
        info_center_raw: str | None = None,
        baby_carriage_raw: str | None = None,
        pet_raw: str | None = None,
        credit_card_raw: str | None = None,
        restroom_raw: str | None = None,
    ) -> None:
        if parse_status not in _VALID_PARSE_STATUSES:
            raise ValueError("유효하지 않은 parse_status입니다.")
        # detail_fetch_status 판정에는 주차·요금·안내처를 넣지 않는다. 넣으면 운영시간이
        # 없고 주차만 있는 장소가 empty에서 success로 바뀌어 재조회 주기가 달라진다 —
        # 이 컬럼은 운영정보 확보 여부를 뜻하므로 기존 의미를 유지한다(D-056).
        detail_status = (
            "empty"
            if operating_hours_raw is None and rest_date_raw is None
            else "success"
        )
        await self._request(
            "PATCH",
            "/places",
            params={"content_id": f"eq.{content_id}"},
            json={
                "operating_hours_raw": operating_hours_raw,
                "rest_date_raw": rest_date_raw,
                "parking_info_raw": parking_info_raw,
                "parking_fee_raw": parking_fee_raw,
                "use_fee_raw": use_fee_raw,
                "discount_info_raw": discount_info_raw,
                "info_center_raw": info_center_raw,
                "baby_carriage_raw": baby_carriage_raw,
                "pet_raw": pet_raw,
                "credit_card_raw": credit_card_raw,
                "restroom_raw": restroom_raw,
                "operating_schedule": operating_schedule,
                "operating_parse_status": parse_status,
                "operating_parser_version": parser_version,
                "detail_fetched_at": _iso(fetched_at),
                "detail_fetch_status": detail_status,
                "detail_error_code": None,
            },
            prefer="return=minimal",
        )

    async def mark_detail_failed(self, content_id: str, error_code: str) -> None:
        await self._request(
            "PATCH",
            "/places",
            params={"content_id": f"eq.{content_id}"},
            json={
                "detail_fetch_status": "failed",
                "detail_error_code": error_code,
            },
            prefer="return=minimal",
        )

    async def update_parsed_schedule(
        self,
        content_id: str,
        operating_schedule: Mapping[str, object] | None,
        parse_status: str,
        parser_version: str,
    ) -> None:
        if parse_status not in _VALID_PARSE_STATUSES:
            raise ValueError("유효하지 않은 parse_status입니다.")
        await self._request(
            "PATCH",
            "/places",
            params={"content_id": f"eq.{content_id}"},
            json={
                "operating_schedule": operating_schedule,
                "operating_parse_status": parse_status,
                "operating_parser_version": parser_version,
            },
            prefer="return=minimal",
        )

    async def reactivate_source_missing_places(
        self,
        content_ids: Sequence[str],
    ) -> int:
        if not content_ids:
            return 0
        changed = 0
        for chunk in _chunks(content_ids, _UPSERT_CHUNK_SIZE):
            quoted_ids = ",".join(f'"{content_id}"' for content_id in chunk)
            response = await self._request(
                "PATCH",
                "/places",
                params={
                    "content_id": f"in.({quoted_ids})",
                    "inactive_reason": "eq.missing_from_source",
                },
                json={
                    "is_active": True,
                    "inactive_reason": None,
                    "inactive_at": None,
                },
                prefer="return=representation",
            )
            payload = self._json(response)
            if not isinstance(payload, list):
                raise SupabaseRepositoryError("invalid reactivate response")
            changed += len(payload)
        return changed

    async def deactivate_unseen_places(
        self,
        area_code: str,
        district_code: str,
        sync_run_id: UUID,
        inactive_at: datetime,
    ) -> int:
        response = await self._request(
            "PATCH",
            "/places",
            params={
                "area_code": f"eq.{area_code}",
                "district_code": f"eq.{district_code}",
                "is_active": "eq.true",
                "or": (
                    f"(last_sync_run_id.neq.{sync_run_id},"
                    "last_sync_run_id.is.null)"
                ),
            },
            json={
                "is_active": False,
                "inactive_reason": "missing_from_source",
                "inactive_at": _iso(inactive_at),
            },
            prefer="return=representation",
        )
        payload = self._json(response)
        if not isinstance(payload, list):
            raise SupabaseRepositoryError("invalid deactivate response")
        return len(payload)

    async def complete_sync_run(
        self,
        sync_run_id: UUID,
        *,
        status: str,
        api_total_count: int | None,
        processed_count: int,
        success_count: int,
        failed_count: int,
        new_count: int,
        updated_count: int,
        deactivated_count: int,
        detail_attempted_count: int,
        error_summary: Mapping[str, object] | None = None,
        completed_at: datetime,
    ) -> None:
        if status not in _VALID_RUN_STATUSES:
            raise ValueError("유효하지 않은 동기화 종료 상태입니다.")
        await self._request(
            "PATCH",
            "/place_sync_runs",
            params={"id": f"eq.{sync_run_id}"},
            json={
                "status": status,
                "api_total_count": api_total_count,
                "processed_count": processed_count,
                "success_count": success_count,
                "failed_count": failed_count,
                "new_count": new_count,
                "updated_count": updated_count,
                "deactivated_count": deactivated_count,
                # 일일 한도 판단의 근거가 되는 값이라 실행 기록에 남긴다. 메모리
                # 집계는 재시작하면 사라지고 스크립트 실행분도 놓친다.
                "detail_attempted_count": detail_attempted_count,
                "error_summary": error_summary,
                "completed_at": _iso(completed_at),
            },
            prefer="return=minimal",
        )

    # --- 개발자 Ops 패널 조회 전용 --------------------------------------------
    # 동기화 파이프라인은 쓰지 않는다. 여기 값이 틀려도 동기화 판정은 달라지지 않는다.

    async def count_rows(self, table: str, filters: Mapping[str, str] | None = None) -> int:
        """PostgREST Content-Range로 행 수만 받는다(본문 전송 없음)."""
        response = await self._request(
            "HEAD",
            f"/{table}",
            params={**(filters or {}), "select": "*"},
            prefer="count=exact",
        )
        total = response.headers.get("content-range", "").partition("/")[2]
        try:
            return int(total)
        except ValueError:
            raise SupabaseRepositoryError(f"invalid count for {table}") from None

    async def get_place_summaries_by_district(self) -> dict[str, object]:
        """적재된 구별 요약과 전 구 합계를 한 번의 페이징으로 만든다.

        구마다 따로 질의하면 왕복이 구 수만큼 늘고, 그보다 먼저 "어떤 구가 적재돼
        있는가"를 알아야 질의를 만들 수 있다. 그 목록을 코드에 박으면 구를 새로
        넣을 때마다 적재와 조회 두 곳을 고쳐야 한다. 전량을 한 번 훑어
        (area_code, district_code)로 묶으면 적재된 구가 결과에서 그대로 드러난다.

        전량이라 해도 세 개 구 2,300행 남짓에 열은 일곱 개뿐이라, 상태별로 count
        질의를 나누는 것보다 싸다.
        """
        rows = await self._fetch_place_summary_rows()

        grouped: dict[tuple[str, str], list[Mapping[str, object]]] = {}
        for row in rows:
            key = (
                str(row.get("area_code") or ""),
                str(row.get("district_code") or ""),
            )
            grouped.setdefault(key, []).append(row)

        return {
            "overall": _summarize_places(rows),
            "districts": [
                {
                    "area_code": area_code,
                    "district_code": district_code,
                    **_summarize_places(group),
                }
                for (area_code, district_code), group in sorted(grouped.items())
            ],
        }

    async def _fetch_place_summary_rows(self) -> list[Mapping[str, object]]:
        """요약에 필요한 일곱 열만 전량 받는다. PostgREST는 한 응답에 1000행까지다."""
        rows: list[Mapping[str, object]] = []
        offset = 0
        while True:
            response = await self._request(
                "GET",
                "/places",
                params={
                    "select": _PLACE_SUMMARY_COLUMNS,
                    "order": "content_id.asc",
                    "limit": str(_READ_PAGE_SIZE),
                    "offset": str(offset),
                },
            )
            page = self._json(response)
            if not isinstance(page, list):
                raise SupabaseRepositoryError("invalid place summary response")
            for raw in page:
                if not isinstance(raw, Mapping):
                    raise SupabaseRepositoryError("invalid place summary row")
                rows.append(raw)
            if len(page) < _READ_PAGE_SIZE:
                break
            offset += _READ_PAGE_SIZE
        return rows

    async def list_region_place_rows(
        self,
        area_code: str,
        district_code: str,
        columns: Sequence[str],
        *,
        active_only: bool = True,
    ) -> list[Mapping[str, object]]:
        """구 하나의 장소 행을 요청한 열만 페이징해 전부 읽는다.

        열 목록을 호출자가 준다 — 이 저장소가 스냅샷 CSV 형식을 알 필요가 없고,
        형식을 아는 쪽(`place_snapshot.SNAPSHOT_COLUMNS`)에 열 정의가 하나만 남는다.

        기본은 활성 장소만이다. 비활성 장소는 목록에서 사라져서 비활성이 된 것이라,
        스냅샷에 넣으면 대조할 때마다 계속 "삭제"로 잡힌다.
        """
        params_base: dict[str, str] = {
            "select": ",".join(columns),
            "area_code": f"eq.{area_code}",
            "district_code": f"eq.{district_code}",
            "order": "content_id.asc",
        }
        if active_only:
            params_base["is_active"] = "eq.true"

        rows: list[Mapping[str, object]] = []
        offset = 0
        while True:
            response = await self._request(
                "GET",
                "/places",
                params={
                    **params_base,
                    "limit": str(_READ_PAGE_SIZE),
                    "offset": str(offset),
                },
            )
            page = self._json(response)
            if not isinstance(page, list):
                raise SupabaseRepositoryError("invalid place row response")
            for raw in page:
                if not isinstance(raw, Mapping):
                    raise SupabaseRepositoryError("invalid place row")
                rows.append(raw)
            if len(page) < _READ_PAGE_SIZE:
                break
            offset += _READ_PAGE_SIZE
        return rows

    async def summarize_detail_calls_since(self, since: datetime) -> dict[str, int]:
        """`since` 이후 시작한 동기화가 부른 detailIntro2 수를 더한다.

        detailIntro2를 부르는 코드는 PlaceSyncService 한 곳뿐이고(추천 경로는 DB에서
        읽는다) 그 경로는 실행마다 place_sync_runs 행을 남긴다. 그래서 호출마다
        카운터를 올리지 않고도 오늘 사용량을 셀 수 있다. 프로세스 메모리 집계와
        달리 서버를 재시작해도 남고, backend/scripts로 돈 실행분도 함께 잡힌다.

        **하한이다.** 재시도는 한 장소를 여러 번 부르지만 여기 세는 것은 장소 수고,
        중간에 죽어 완료 처리를 못 한 실행은 열이 비어 있다. 그래서 비어 있는 실행
        수(`runs_without_count`)를 함께 돌려준다 — 화면이 "관측한 값"과 "재지 못한
        구간"을 구분해 보여줄 수 있어야 한다.
        """
        response = await self._request(
            "GET",
            "/place_sync_runs",
            params={
                "select": "detail_attempted_count",
                "started_at": f"gte.{_iso(since)}",
            },
        )
        payload = self._json(response)
        if not isinstance(payload, list):
            raise SupabaseRepositoryError("invalid sync run summary response")

        total = 0
        runs = 0
        runs_without_count = 0
        for row in payload:
            if not isinstance(row, Mapping):
                raise SupabaseRepositoryError("invalid sync run summary row")
            runs += 1
            value = row.get("detail_attempted_count")
            if value is None:
                runs_without_count += 1
                continue
            total += int(value)
        return {
            "count": total,
            "runs": runs,
            "runs_without_count": runs_without_count,
        }

    async def list_recent_sync_runs(self, limit: int = 10) -> list[dict[str, object]]:
        response = await self._request(
            "GET",
            "/place_sync_runs",
            params={
                "select": "*",
                "order": "started_at.desc",
                "limit": str(limit),
            },
        )
        payload = self._json(response)
        if not isinstance(payload, list):
            raise SupabaseRepositoryError("invalid sync run list response")
        return [dict(row) for row in payload if isinstance(row, Mapping)]

    async def find_missing_concentration_mappings(
        self, content_ids: Sequence[str]
    ) -> list[str]:
        """집중률 매핑이 없는 content_id를 가려낸다.

        매핑이 없는 장소는 혼잡도 조회를 **아예 하지 않고** no_data로 끝난다
        (`enrichment_service._enrich_candidate`). 동기화로 새로 들어온 장소는
        매핑이 당연히 없으므로, 알리지 않으면 그 장소만 조용히 혼잡도 판정에서
        빠진 채로 남는다. 매핑 적재는 별도 스크립트 소관이라 여기서는 사실만
        확인한다.
        """
        if not content_ids:
            return []
        found: set[str] = set()
        for chunk in _chunks(list(content_ids), _UPSERT_CHUNK_SIZE):
            quoted = ",".join(f'"{content_id}"' for content_id in chunk)
            response = await self._request(
                "GET",
                "/place_concentration_mappings",
                params={"select": "content_id", "content_id": f"in.({quoted})"},
            )
            payload = self._json(response)
            if not isinstance(payload, list):
                raise SupabaseRepositoryError("invalid concentration mapping response")
            for row in payload:
                if isinstance(row, Mapping) and row.get("content_id"):
                    found.add(str(row["content_id"]))
        return [content_id for content_id in content_ids if content_id not in found]

    async def list_sync_locks(self) -> list[dict[str, object]]:
        """현재 잡혀 있는 동기화 잠금. 만료된 행도 그대로 보여준다.

        만료를 여기서 걸러내면 "잠금이 남아 실행이 막힌다"와 "잠금이 없다"가
        화면에서 같아 보인다. 판단은 화면에서 하도록 시각을 그대로 넘긴다.
        """
        response = await self._request(
            "GET",
            "/place_sync_locks",
            params={"select": "*", "order": "acquired_at.desc"},
        )
        payload = self._json(response)
        if not isinstance(payload, list):
            raise SupabaseRepositoryError("invalid sync lock list response")
        return [dict(row) for row in payload if isinstance(row, Mapping)]


def _summarize_places(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """장소 행 묶음의 활성 수와 상태 분포를 센다.

    구별 요약과 전 구 합계가 같은 함수를 쓴다 — 따로 세면 한쪽만 규칙이 바뀐 채
    남는 이중 경로가 생긴다.
    """
    active = 0
    detail_status: dict[str, int] = {}
    parse_status: dict[str, int] = {}
    parser_versions: dict[str, int] = {}
    latest_detail_fetched_at: datetime | None = None
    for raw in rows:
        if raw.get("is_active"):
            active += 1
        _bump(detail_status, raw.get("detail_fetch_status"))
        _bump(parse_status, raw.get("operating_parse_status"))
        _bump(parser_versions, raw.get("operating_parser_version"))
        fetched_at = _parse_datetime(raw.get("detail_fetched_at"), "detail_fetched_at")
        if fetched_at is not None and (
            latest_detail_fetched_at is None or fetched_at > latest_detail_fetched_at
        ):
            latest_detail_fetched_at = fetched_at

    return {
        "total": len(rows),
        "active": active,
        "inactive": len(rows) - active,
        "detail_fetch_status": detail_status,
        "operating_parse_status": parse_status,
        "operating_parser_version": parser_versions,
        "latest_detail_fetched_at": _iso(latest_detail_fetched_at),
    }


def _bump(counter: dict[str, int], value: object) -> None:
    key = str(value) if value is not None else "null"
    counter[key] = counter.get(key, 0) + 1


def _to_evidence_match(row: object) -> PlaceEvidenceMatch:
    if not isinstance(row, Mapping):
        raise SupabaseRepositoryError("invalid evidence row")
    raw_snippets = row.get("evidence")
    snippets = (
        tuple(_to_evidence_snippet(item) for item in raw_snippets)
        if isinstance(raw_snippets, list)
        else ()
    )
    return PlaceEvidenceMatch(
        content_id=str(row["content_id"]),
        place_title=str(row.get("place_title") or ""),
        avg_similarity=float(row["avg_similarity"]),
        snippets=snippets,
    )


def _to_evidence_snippet(item: object) -> PlaceEvidenceSnippet:
    if not isinstance(item, Mapping):
        raise SupabaseRepositoryError("invalid evidence snippet")
    published_at = item.get("published_at")
    return PlaceEvidenceSnippet(
        source_text=str(item.get("source_text") or ""),
        source_url=str(item["source_url"]) if item.get("source_url") else None,
        similarity=float(item["similarity"]),
        published_at=(
            datetime.fromisoformat(str(published_at)) if published_at else None
        ),
    )
