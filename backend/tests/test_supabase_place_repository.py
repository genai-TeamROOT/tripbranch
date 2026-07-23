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
            error_summary={"TOUR_DETAIL_TIMEOUT": 1},
            completed_at=NOW,
        )

    assert seen_payload["status"] == "partial_failure"
    assert seen_payload["failed_count"] == 1
    assert seen_payload["error_summary"] == {"TOUR_DETAIL_TIMEOUT": 1}


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
