from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.domain.models import StoredPlaceState, TourPlaceRecord
from app.repositories.supabase_places import (
    SupabasePlaceRepository,
    SupabaseRepositoryError,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 7, 24, 3, 0, tzinfo=UTC)


def _repository(
    handler: httpx.MockTransport,
    client: httpx.AsyncClient,
) -> SupabasePlaceRepository:
    return SupabasePlaceRepository(
        supabase_url="https://project.supabase.co/",
        secret_key="sb_secret_test",
        client=client,
    )


def _place(content_id: str) -> TourPlaceRecord:
    return TourPlaceRecord(
        content_id=content_id,
        content_type_id="12",
        title=f"장소 {content_id}",
        address="서울특별시 종로구",
        latitude=37.57,
        longitude=126.97,
        area_code="11",
        district_code="110",
        lcls_systm1="VE",
        lcls_systm2="VE01",
        lcls_systm3="VE010100",
        source_modified_at=NOW,
    )


@pytest.mark.asyncio
async def test_create_sync_run_uses_secret_key_header() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(201, json=[{"id": str(RUN_ID)}])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await _repository(transport, client).create_sync_run("11", "110")

    request = seen["request"]
    assert isinstance(request, httpx.Request)
    assert request.url.path == "/rest/v1/place_sync_runs"
    assert request.headers["apikey"] == "sb_secret_test"
    assert "authorization" not in request.headers
    assert request.headers["prefer"] == "return=representation"
    assert request.read() == b'{"area_code":"11","district_code":"110"}'
    assert result == RUN_ID


@pytest.mark.asyncio
async def test_lock_rpcs_send_exact_database_arguments() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=True)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        repository = _repository(transport, client)
        acquired = await repository.try_acquire_sync_lock(
            "11", "110", RUN_ID, "2 hours"
        )
        released = await repository.release_sync_lock("11", "110", RUN_ID)

    assert acquired is True
    assert released is True
    assert [request.url.path for request in seen] == [
        "/rest/v1/rpc/try_acquire_place_sync_lock",
        "/rest/v1/rpc/release_place_sync_lock",
    ]
    assert b'"p_lock_ttl":"2 hours"' in seen[0].read()
    assert str(RUN_ID).encode() in seen[1].read()


@pytest.mark.asyncio
async def test_find_active_places_by_name_reads_coordinates_and_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/v1/places"
        assert request.url.params["title"] == "eq.쌈지길"
        assert request.url.params["is_active"] == "eq.true"
        return httpx.Response(
            200,
            json=[
                {
                    "content_id": "128553",
                    "title": "쌈지길",
                    "address": "서울특별시 종로구 인사동길 44",
                    "latitude": 37.5743062352,
                    "longitude": 126.9848674428,
                    "place_concentration_mappings": [
                        {"primary_concentration_name": "쌈지길"}
                    ],
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        locations = await _repository(transport, client).find_active_places_by_name(
            "쌈지길"
        )

    assert len(locations) == 1
    assert locations[0].content_id == "128553"
    assert locations[0].concentration_name == "쌈지길"


@pytest.mark.asyncio
async def test_find_active_places_by_name_falls_back_through_title_variants() -> None:
    """정확 일치 → 지역 접두사 → 공백 무시 → 괄호 부기 → 별칭 순으로 넓힌다(D-043).

    지역 검색은 "북촌 한옥마을"을 주는데 저장소는 "북촌한옥마을"이고, 사용자는
    "종묘"라고 하는데 저장소 제목은 "종묘 [유네스코 세계유산]"이다.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        title = request.url.params.get("title")
        alias = request.url.params.get(
            "place_concentration_mappings.concentration_aliases"
        )
        seen.append(title if title is not None else f"alias:{alias}")
        if title == "ilike.종묘 [*":
            return httpx.Response(
                200,
                json=[
                    {
                        "content_id": "126510",
                        "title": "종묘 [유네스코 세계유산]",
                        "address": None,
                        "latitude": 37.5739,
                        "longitude": 126.9945,
                        "place_concentration_mappings": {
                            "primary_concentration_name": "종묘 [유네스코 세계유산]",
                            "concentration_search_keys": ["종묘"],
                        },
                    }
                ],
            )
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        locations = await _repository(transport, client).find_active_places_by_name("종묘")

    assert seen == ["eq.종묘", "ilike.서울 종묘", "ilike.종묘 [*"]
    assert len(locations) == 1
    assert locations[0].concentration_name == "종묘 [유네스코 세계유산]"
    # 조회는 검색어로, 대조는 정식 명칭으로 해야 종묘광장공원과 섞이지 않는다.
    assert locations[0].concentration_search_keys == ("종묘",)


@pytest.mark.asyncio
async def test_find_active_places_by_name_finds_seoul_prefixed_title() -> None:
    """사용자는 "명동성당"이라고 하는데 저장소 제목은 "서울 명동성당"이다.

    TourAPI가 국가지정문화재류에 붙이는 접두사이고 활성 26곳이 여기 걸린다.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        title = request.url.params.get("title")
        seen.append(title if title is not None else "alias")
        if title == "ilike.서울 명동성당":
            return httpx.Response(
                200,
                json=[
                    {
                        "content_id": "126804",
                        "title": "서울 명동성당",
                        "address": "서울특별시 중구 명동길 74 (명동2가)",
                        "latitude": 37.56367587,
                        "longitude": 126.9867758233,
                        "place_concentration_mappings": [],
                    }
                ],
            )
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        locations = await _repository(transport, client).find_active_places_by_name(
            "명동성당"
        )

    assert seen == ["eq.명동성당", "ilike.서울 명동성당"]
    assert len(locations) == 1
    assert locations[0].content_id == "126804"
    assert locations[0].title == "서울 명동성당"


@pytest.mark.asyncio
async def test_find_active_places_by_name_prefers_exact_title_over_prefix() -> None:
    """접두사 없는 동명 장소가 생기면 그쪽이 이긴다 - 접두사 조회까지 가지 않는다."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        title = request.url.params.get("title")
        seen.append(title if title is not None else "alias")
        if title == "eq.명동성당":
            return httpx.Response(
                200,
                json=[
                    {
                        "content_id": "999999",
                        "title": "명동성당",
                        "address": None,
                        "latitude": 37.5636,
                        "longitude": 126.9867,
                        "place_concentration_mappings": [],
                    }
                ],
            )
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        locations = await _repository(transport, client).find_active_places_by_name(
            "명동성당"
        )

    assert seen == ["eq.명동성당"]
    assert locations[0].content_id == "999999"


@pytest.mark.asyncio
async def test_find_active_places_by_name_does_not_double_prefix() -> None:
    """정식 제목을 그대로 넣어도 "서울 서울 ..."을 조회하지 않는다."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        title = request.url.params.get("title")
        seen.append(title if title is not None else "alias")
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await _repository(transport, client).find_active_places_by_name("서울 명동성당")

    assert "ilike.서울 서울 명동성당" not in seen


@pytest.mark.asyncio
async def test_find_active_places_by_name_uses_mapping_alias_as_last_resort() -> None:
    """"창덕궁"은 저장소 제목이 "창덕궁과 후원 [유네스코 세계유산]"이라 제목 규칙으로
    닿지 않는다. 접두 매칭으로 넓히면 창덕궁 낙선재·약다방까지 걸리므로 사람이 지정한
    별칭으로만 잇는다.
    """
    alias_filters: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        alias = request.url.params.get(
            "place_concentration_mappings.concentration_aliases"
        )
        if alias is None:
            return httpx.Response(200, json=[])
        alias_filters.append(alias)
        assert "!inner" in request.url.params["select"]
        return httpx.Response(
            200,
            json=[
                {
                    "content_id": "127642",
                    "title": "창덕궁과 후원 [유네스코 세계유산]",
                    "address": None,
                    "latitude": 37.5794,
                    "longitude": 126.9910,
                    "place_concentration_mappings": {
                        "primary_concentration_name": "창덕궁과 후원 [유네스코 세계유산]",
                        "concentration_search_keys": ["창덕궁과", "후원"],
                    },
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        locations = await _repository(transport, client).find_active_places_by_name(
            "창덕궁"
        )

    assert alias_filters == ["cs.{창덕궁}"]
    assert len(locations) == 1
    assert locations[0].title == "창덕궁과 후원 [유네스코 세계유산]"
    assert locations[0].concentration_search_keys == ("창덕궁과", "후원")


@pytest.mark.asyncio
async def test_get_region_place_states_maps_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["area_code"] == "eq.11"
        assert request.url.params["district_code"] == "eq.110"
        return httpx.Response(
            200,
            json=[
                {
                    "content_id": "126508",
                    "source_modified_at": "2026-07-23T15:30:45+00:00",
                    "detail_fetched_at": None,
                    "detail_fetch_status": "pending",
                    "operating_parser_version": "operating-hours-1.0.0",
                    "operating_hours_raw": None,
                    "rest_date_raw": None,
                    "is_active": True,
                    "inactive_reason": None,
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        states = await _repository(
            transport, client
        ).get_region_place_states("11", "110")

    assert states["126508"].detail_fetch_status == "pending"
    assert states["126508"].source_modified_at == datetime(
        2026, 7, 23, 15, 30, 45, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_upsert_chunks_by_100_and_preserves_existing_manual_state() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201)

    manual_state = StoredPlaceState(
        content_id="0",
        source_modified_at=None,
        detail_fetched_at=NOW,
        detail_fetch_status="success",
        operating_parser_version="operating-hours-1.0.0",
        operating_hours_raw="09:00~18:00",
        rest_date_raw=None,
        is_active=False,
        inactive_reason="manual_exclusion",
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await _repository(transport, client).upsert_place_list(
            [_place(str(index)) for index in range(201)],
            {"0": manual_state},
            RUN_ID,
            NOW,
        )

    assert len(requests) == 3
    request_payloads = [json.loads(request.content) for request in requests]
    assert [len(payload) for payload in request_payloads] == [1, 100, 100]
    assert all(
        len({frozenset(row) for row in payload}) == 1
        for payload in request_payloads
    )
    first_row = request_payloads[0][0]
    assert "operating_hours_raw" not in first_row
    assert "detail_fetch_status" not in first_row
    assert "is_active" not in first_row
    new_row = request_payloads[1][0]
    assert new_row["detail_fetch_status"] == "pending"
    assert new_row["is_active"] is True
    assert requests[0].url.params["on_conflict"] == "content_id"
    assert requests[0].headers["prefer"] == (
        "resolution=merge-duplicates,return=minimal"
    )


@pytest.mark.asyncio
async def test_upsert_reactivates_only_source_missing_place() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.extend(json.loads(request.content))
        return httpx.Response(201)

    missing_state = StoredPlaceState(
        content_id="1",
        source_modified_at=None,
        detail_fetched_at=None,
        detail_fetch_status="failed",
        operating_parser_version="operating-hours-1.0.0",
        operating_hours_raw=None,
        rest_date_raw=None,
        is_active=False,
        inactive_reason="missing_from_source",
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await _repository(transport, client).upsert_place_list(
            [_place("1")], {"1": missing_state}, RUN_ID, NOW
        )

    assert payloads[0]["is_active"] is True
    assert payloads[0]["inactive_reason"] is None
    assert payloads[0]["inactive_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hours", "rest_date", "expected_status"),
    [
        ("09:00~18:00", "매주 화요일", "success"),
        (None, None, "empty"),
    ],
)
async def test_update_operating_details_sets_success_or_empty(
    hours: str | None,
    rest_date: str | None,
    expected_status: str,
) -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await _repository(transport, client).update_operating_details(
            "126508",
            hours,
            rest_date,
            {"availability": "scheduled"} if hours else None,
            "parsed" if hours else "unknown",
            "operating-hours-1.0.0",
            NOW,
        )

    assert seen_payload["detail_fetch_status"] == expected_status
    assert seen_payload["detail_error_code"] is None


@pytest.mark.asyncio
async def test_mark_detail_failed_does_not_overwrite_cached_details() -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await _repository(transport, client).mark_detail_failed(
            "126508", "TOUR_DETAIL_TIMEOUT"
        )

    assert seen_payload == {
        "detail_fetch_status": "failed",
        "detail_error_code": "TOUR_DETAIL_TIMEOUT",
    }


@pytest.mark.asyncio
async def test_update_parsed_schedule_does_not_change_detail_fetched_at() -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await _repository(transport, client).update_parsed_schedule(
            "126508",
            {"availability": "scheduled"},
            "parsed",
            "operating-hours-1.1.0",
        )

    assert seen_payload["operating_parser_version"] == "operating-hours-1.1.0"
    assert "detail_fetched_at" not in seen_payload
    assert "operating_hours_raw" not in seen_payload


@pytest.mark.asyncio
async def test_deactivate_unseen_places_returns_changed_count() -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json=[{"content_id": "old-1"}, {"content_id": "old-2"}])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        changed = await _repository(transport, client).deactivate_unseen_places(
            "11", "110", RUN_ID, NOW
        )

    assert changed == 2
    assert seen_request is not None
    assert seen_request.url.params["is_active"] == "eq.true"
    assert "last_sync_run_id.neq." in seen_request.url.params["or"]
    assert json.loads(seen_request.content)["inactive_reason"] == "missing_from_source"


@pytest.mark.asyncio
async def test_complete_sync_run_updates_counts() -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await _repository(transport, client).complete_sync_run(
            RUN_ID,
            status="partial_failure",
            api_total_count=3,
            processed_count=3,
            success_count=2,
            failed_count=1,
            new_count=3,
            updated_count=0,
            deactivated_count=0,
            detail_attempted_count=3,
            error_summary={"TOUR_DETAIL_TIMEOUT": 1},
            completed_at=NOW,
        )

    assert seen_payload["status"] == "partial_failure"
    assert seen_payload["failed_count"] == 1
    assert seen_payload["error_summary"] == {"TOUR_DETAIL_TIMEOUT": 1}
    # 일일 한도 판단의 근거라 실행 기록에 남아야 한다.
    assert seen_payload["detail_attempted_count"] == 3


@pytest.mark.asyncio
async def test_http_error_does_not_expose_secret_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SupabaseRepositoryError) as exc_info:
            await _repository(transport, client).create_sync_run("11", "110")

    assert "sb_secret_test" not in str(exc_info.value)
    assert "sb_secret_test" not in repr(exc_info.value.details)
    assert exc_info.value.details == {"upstream_detail": "HTTP 401"}


@pytest.mark.asyncio
async def test_find_concentration_mapped_places_reads_single_object_embed() -> None:
    """places ↔ mappings는 1:1이라 PostgREST가 배열이 아닌 단일 객체로 내려준다.

    배열만 처리하던 파서 탓에 concentration_name이 항상 None이 되어 대체 조회가
    후보를 하나도 찾지 못했다(2026-08-03).
    """
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "content_id": "129501",
                    "title": "낙산공원",
                    "address": "서울특별시 종로구 낙산길 41",
                    "latitude": 37.5805179476871,
                    "longitude": 127.006496092905,
                    "place_concentration_mappings": {"primary_concentration_name": "낙산공원"},
                },
                {
                    "content_id": "129502",
                    "title": "매핑없음",
                    "address": None,
                    "latitude": 37.58,
                    "longitude": 127.0,
                    "place_concentration_mappings": None,
                },
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabasePlaceRepository(
            "https://project.supabase.co/", "sb_secret_test", client
        )
        places = await repository.find_concentration_mapped_places()

    assert [place.concentration_name for place in places] == ["낙산공원"]
    assert captured[0].url.params["is_active"] == "eq.true"


@pytest.mark.asyncio
async def test_find_concentration_mapped_places_also_reads_array_embed() -> None:
    """관계 형태가 배열로 바뀌어도 같은 값을 읽는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "content_id": "129501",
                    "title": "낙산공원",
                    "address": None,
                    "latitude": 37.58,
                    "longitude": 127.0,
                    "place_concentration_mappings": [
                        {"primary_concentration_name": "낙산공원"}
                    ],
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabasePlaceRepository(
            "https://project.supabase.co/", "sb_secret_test", client
        )
        places = await repository.find_concentration_mapped_places()

    assert places[0].concentration_name == "낙산공원"


@pytest.mark.asyncio
async def test_count_rows_reads_content_range_total() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, headers={"Content-Range": "*/844"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabasePlaceRepository(
            "https://project.supabase.co/", "sb_secret_test", client
        )
        total = await repository.count_rows("place_enrichments")

    assert total == 844
    assert captured[0].method == "HEAD"
    assert captured[0].headers["prefer"] == "count=exact"


@pytest.mark.asyncio
async def test_count_rows_rejects_missing_content_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabasePlaceRepository(
            "https://project.supabase.co/", "sb_secret_test", client
        )
        with pytest.raises(SupabaseRepositoryError):
            await repository.count_rows("places")


@pytest.mark.asyncio
async def test_place_summaries_split_by_district_and_total() -> None:
    """구별 분포와 전 구 합계를 한 번의 조회로 만든다."""
    rows = [
        {
            "area_code": "11",
            "district_code": "110",
            "is_active": True,
            "detail_fetch_status": "succeeded",
            "operating_parse_status": "parsed",
            "operating_parser_version": "operating-hours-1.0.0",
            "detail_fetched_at": "2026-08-08T05:00:00+00:00",
        },
        {
            "area_code": "11",
            "district_code": "110",
            "is_active": False,
            "detail_fetch_status": "pending",
            "operating_parse_status": "unknown",
            "operating_parser_version": "operating-hours-0.9.0",
            "detail_fetched_at": None,
        },
        {
            "area_code": "11",
            "district_code": "170",
            "is_active": True,
            "detail_fetch_status": "failed",
            "operating_parse_status": "unknown",
            "operating_parser_version": "operating-hours-1.0.0",
            "detail_fetched_at": "2026-08-21T05:00:00+00:00",
        },
    ]

    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json=rows)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabasePlaceRepository(
            "https://project.supabase.co/", "sb_secret_test", client
        )
        summaries = await repository.get_place_summaries_by_district()

    # 구별로 질의를 나누지 않는다 — 나누면 적재된 구 목록을 미리 알아야 한다.
    assert len(requested) == 1
    assert "district_code" not in requested[0].url.params

    districts = summaries["districts"]
    assert isinstance(districts, list)
    assert [(d["area_code"], d["district_code"]) for d in districts] == [
        ("11", "110"),
        ("11", "170"),
    ]

    jongno = districts[0]
    assert (jongno["total"], jongno["active"], jongno["inactive"]) == (2, 1, 1)
    assert jongno["detail_fetch_status"] == {"succeeded": 1, "pending": 1}
    assert jongno["latest_detail_fetched_at"] == "2026-08-08T05:00:00+00:00"

    yongsan = districts[1]
    assert (yongsan["total"], yongsan["active"], yongsan["inactive"]) == (1, 1, 0)
    assert yongsan["latest_detail_fetched_at"] == "2026-08-21T05:00:00+00:00"

    overall = summaries["overall"]
    assert isinstance(overall, dict)
    assert (overall["total"], overall["active"], overall["inactive"]) == (3, 2, 1)
    assert overall["detail_fetch_status"] == {
        "succeeded": 1,
        "pending": 1,
        "failed": 1,
    }
    assert overall["operating_parse_status"] == {"parsed": 1, "unknown": 2}
    # 파서 버전이 섞여 있으면 다음 동기화에서 재파싱 대상이 생긴다는 신호다.
    assert overall["operating_parser_version"] == {
        "operating-hours-1.0.0": 2,
        "operating-hours-0.9.0": 1,
    }
    # 합계의 최신 상세조회 시각은 전 구를 통틀어 가장 나중이다.
    assert overall["latest_detail_fetched_at"] == "2026-08-21T05:00:00+00:00"


@pytest.mark.asyncio
async def test_list_sync_locks_keeps_expired_rows() -> None:
    """만료된 잠금을 저장소에서 걸러내면 '잠금 없음'과 구분되지 않는다."""
    expired = {
        "area_code": "11",
        "district_code": "110",
        "sync_run_id": str(RUN_ID),
        "acquired_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-08-01T02:00:00+00:00",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[expired])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabasePlaceRepository(
            "https://project.supabase.co/", "sb_secret_test", client
        )
        locks = await repository.list_sync_locks()

    assert locks == [expired]


@pytest.mark.asyncio
async def test_find_missing_concentration_mappings_returns_unmapped_ids() -> None:
    """매핑 없는 장소는 혼잡도 조회를 아예 건너뛰므로 누가 빠졌는지 알아야 한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"content_id": "2"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabasePlaceRepository(
            "https://project.supabase.co/", "sb_secret_test", client
        )
        missing = await repository.find_missing_concentration_mappings(["1", "2", "3"])

    assert missing == ["1", "3"]


@pytest.mark.asyncio
async def test_find_missing_concentration_mappings_skips_request_when_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("빈 목록에는 요청을 보내지 않아야 한다")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabasePlaceRepository(
            "https://project.supabase.co/", "sb_secret_test", client
        )
        assert await repository.find_missing_concentration_mappings([]) == []


@pytest.mark.asyncio
async def test_detail_call_summary_separates_unmeasured_runs() -> None:
    """재지 못한 실행을 0으로 합치면 합계가 실제보다 정확해 보인다."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=[
                {"detail_attempted_count": 486},
                {"detail_attempted_count": 3},
                # 중간에 죽어 완료 처리를 못 한 실행, 또는 열 추가 이전 행.
                {"detail_attempted_count": None},
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabasePlaceRepository(
            "https://project.supabase.co/", "sb_secret_test", client
        )
        summary = await repository.summarize_detail_calls_since(NOW)

    assert summary == {"count": 489, "runs": 3, "runs_without_count": 1}
    # 오늘 것만 세야 한다 — 경계를 안 걸면 누적 전체가 오늘 사용량으로 보인다.
    assert captured[0].url.params["started_at"].startswith("gte.")
