"""개발자 Ops 패널 API(/api/dev/*) 테스트."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from app.observability import api_usage
from app.routes import dev as dev_routes


@pytest.fixture(autouse=True)
def _clean_registry():
    api_usage.reset_usage()
    yield
    api_usage.reset_usage()


def _client() -> TestClient:
    return TestClient(create_app())


def test_dev_routes_are_absent_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """배포 환경에서는 경로 자체가 없어야 한다 — 설정 플래그가 아니라 미등록으로 막는다."""
    monkeypatch.setattr(settings, "app_env", "production")
    with _client() as client:
        assert client.get("/api/dev/api-usage").status_code == 404
        assert client.get("/api/dev/db-status").status_code == 404


def test_api_usage_returns_snapshot_with_provider_modes() -> None:
    api_usage.record_call("tour_api", "detailIntro2", ok=True, latency_ms=12, status="200")

    with _client() as client:
        response = client.get("/api/dev/api-usage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["totals"]["count"] == 1
    entry = payload["entries"][0]
    assert (entry["provider"], entry["operation"]) == ("tour_api", "detailIntro2")
    assert entry["daily_limit"] == settings.tour_api_daily_call_limit
    # Fake 구성으로 떠 있으면 표가 비는 게 정상이라 모드를 함께 내려야 화면이
    # "호출 없음"과 "fake라 호출 자체가 없음"을 구분할 수 있다.
    assert payload["provider_modes"]["place"] in {"fake", "real"}


def test_api_usage_reset_clears_counters() -> None:
    api_usage.record_call("tour_api", "detailIntro2", ok=True, latency_ms=12, status="200")

    with _client() as client:
        payload = client.post("/api/dev/api-usage/reset").json()

    assert payload["totals"]["count"] == 0
    assert payload["entries"] == []


def test_db_status_requires_supabase_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_secret_key", "")

    with _client() as client:
        response = client.get("/api/dev/db-status")

    assert response.status_code == 400
    assert "SUPABASE_URL" in response.json()["error"]["message"]


def test_db_status_aggregates_places_runs_and_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Range": "*/12"})
        if path.endswith("/places"):
            return httpx.Response(
                200,
                json=[
                    {
                        "is_active": True,
                        "detail_fetch_status": "succeeded",
                        "operating_parse_status": "parsed",
                        "operating_parser_version": "operating-hours-1.0.0",
                        "detail_fetched_at": "2026-08-08T05:00:00+00:00",
                    }
                ],
            )
        if path.endswith("/place_sync_runs"):
            return httpx.Response(200, json=[{"id": "run-1", "status": "success"}])
        if path.endswith("/place_sync_locks"):
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(
        dev_routes,
        "status_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with _client() as client:
        payload = client.get("/api/dev/db-status").json()

    assert payload["area_code"] == settings.place_sync_area_code
    assert payload["places"]["total"] == 1
    assert payload["places"]["active"] == 1
    assert payload["place_enrichments_count"] == 12
    assert payload["place_concentration_mappings_count"] == 12
    assert payload["sync_runs"] == [{"id": "run-1", "status": "success"}]
    assert payload["sync_locks"] == []
    assert payload["detail_ttl_days"] == settings.place_sync_detail_ttl_days


def test_db_status_does_not_count_itself_in_api_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """패널의 상태 조회가 자기 호출량 표에 잡히면 안 된다.

    잡히면 새로고침 한 번에 place_sync_runs·place_sync_locks 등이 늘어나,
    추천 요청이 동기화 테이블을 읽은 것처럼 보인다(추천 경로는 place_sync_*를
    읽지 않는다). 측정 도구가 측정값을 만드는 상태라 회귀로 막는다.
    """
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Range": "*/0"})
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        dev_routes,
        "status_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with _client() as client:
        assert client.get("/api/dev/db-status").status_code == 200
        usage = client.get("/api/dev/api-usage").json()

    assert usage["entries"] == []
    assert usage["totals"]["count"] == 0
