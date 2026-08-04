"""Supabase PostgREST를 사용하는 장소 동기화 저장소."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TypeVar
from uuid import UUID

import httpx

from app.domain.models import (
    StoredPlaceDetail,
    StoredPlaceLocation,
    StoredPlaceState,
    TourPlaceRecord,
)
from app.errors import AppError

_READ_PAGE_SIZE = 1000
_UPSERT_CHUNK_SIZE = 100
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
    "place_concentration_mappings(primary_concentration_name,concentration_search_key)"
)

_DETAIL_COLUMNS = ",".join(
    (
        "content_id",
        "content_type_id",
        "title",
        "address",
        "operating_hours_raw",
        "rest_date_raw",
        "detail_fetch_status",
        "detail_fetched_at",
        "source_modified_at",
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
        concentration_search_key = (
            _optional_text(mapping.get("concentration_search_key"))
            if isinstance(mapping, Mapping)
            else None
        )
        locations.append(
            StoredPlaceLocation(
                content_id=str(raw["content_id"]),
                title=str(raw.get("title") or fallback_title),
                address=_optional_text(raw.get("address")),
                latitude=latitude,
                longitude=longitude,
                concentration_name=concentration_name,
                concentration_search_key=concentration_search_key,
            )
        )
    return tuple(locations)


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


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

        다만 공백 유무는 표기 차이로 본다. 지역 검색은 "북촌 한옥마을"을 주는데
        저장소에는 "북촌한옥마을"로 들어 있어, 정확 일치만 보면 같은 장소를 놓친다.
        """
        normalized_name = name.strip()
        if not normalized_name:
            return ()
        rows = await self._query_places_by_title(f"eq.{normalized_name}")
        if not rows and any(character.isspace() for character in normalized_name):
            # 공백 자리에 와일드카드를 넣어 "북촌 한옥마을" → "북촌한옥마을"을 잇는다.
            # PostgREST는 ilike의 `*`를 `%`로 바꿔 주므로 인코딩 문제가 없다.
            pattern = "*".join(normalized_name.split())
            rows = await self._query_places_by_title(f"ilike.{pattern}")

        return _map_place_locations(rows, fallback_title=normalized_name)

    async def _query_places_by_title(self, title_filter: str) -> list[object]:
        response = await self._request(
            "GET",
            "/places",
            params={
                "select": _LOCATION_COLUMNS,
                "title": title_filter,
                "is_active": "eq.true",
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
                    operating_hours_raw=_optional_text(raw.get("operating_hours_raw")),
                    rest_date_raw=_optional_text(raw.get("rest_date_raw")),
                    detail_fetch_status=str(raw.get("detail_fetch_status") or ""),
                    detail_fetched_at=_parse_datetime(
                        raw.get("detail_fetched_at"), "detail_fetched_at"
                    ),
                    source_modified_at=_parse_datetime(
                        raw.get("source_modified_at"), "source_modified_at"
                    ),
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
    ) -> None:
        if parse_status not in _VALID_PARSE_STATUSES:
            raise ValueError("유효하지 않은 parse_status입니다.")
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
                "error_summary": error_summary,
                "completed_at": _iso(completed_at),
            },
            prefer="return=minimal",
        )
