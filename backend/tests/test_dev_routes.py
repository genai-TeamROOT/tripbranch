"""개발자 Ops 패널 API(/api/dev/*) 테스트."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from app.observability import api_usage
from app.routes import dev as dev_routes
from app.services import place_snapshot
from app.services.place_sync import PlaceSyncResult, SyncProgress
from app.services.place_sync_jobs import get_job_registry


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


@pytest.fixture(autouse=True)
def _clean_jobs():
    get_job_registry().reset()
    yield
    get_job_registry().reset()


@pytest.fixture
def _real_place(monkeypatch: pytest.MonkeyPatch) -> None:
    """동기화 실행 조건(PLACE_PROVIDER=real)만 만든다.

    provider_mode 자체를 real로 올리면 llm·weather·geocoding·local_search까지
    real이 되어 부팅 검증(validate_provider_config)이 그 키들을 전부 요구한다.
    로컬에는 backend/.env에 값이 있고 CI에는 없어 CI에서만 깨진다. 아래에서 real
    전용 키를 명시적으로 비워 로컬에서도 CI와 같은 조건으로 돌게 한다.
    """
    monkeypatch.setattr(settings, "provider_mode", "fake")
    monkeypatch.setattr(settings, "place_provider", "real")
    monkeypatch.setattr(settings, "tour_api_service_key", "tour-key")
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")
    for attribute in (
        "llm_api_key",
        "weather_api_key",
        "naver_map_client_id",
        "naver_map_client_secret",
        "naver_local_search_client_id",
        "naver_local_search_client_secret",
    ):
        monkeypatch.setattr(settings, attribute, "")


def _snapshot_row(content_id: str, **overrides: str) -> dict[str, str]:
    row = {
        "content_id": content_id,
        "content_type_id": "12",
        "title": f"장소 {content_id}",
        "address": "서울특별시 종로구",
        "latitude": "37.5",
        "longitude": "127.0",
        "area_code": "11",
        "district_code": "110",
        "lcls_systm1": "VE",
        "lcls_systm2": "VE01",
        "lcls_systm3": "VE010100",
        "source_modified_at": "2026-08-01T00:00:00+09:00",
        "first_image_url": "",
        "thumbnail_url": "",
        "list_fetched_at": "2026-08-08T13:00:00+09:00",
    }
    row.update(overrides)
    return row


def test_place_sync_refuses_fake_place_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fake 데이터가 운영 places에 upsert되는 사고를 막는다(D-042와 같은 함정)."""
    monkeypatch.setattr(settings, "provider_mode", "fake")
    monkeypatch.setattr(settings, "place_provider", "fake")

    with _client() as client:
        response = client.post("/api/dev/place-sync/reconcile", json={})

    assert response.status_code == 400
    assert "PLACE_PROVIDER" in response.json()["error"]["message"]


def test_apply_rejects_mismatched_confirm(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    monkeypatch.setattr(place_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    place_snapshot.write_snapshot({"1": _snapshot_row("1")}, tmp_path / "snap.csv")

    with _client() as client:
        response = client.post(
            "/api/dev/place-sync/apply",
            json={
                "snapshot": "snap.csv",
                "detail_content_ids": ["1"],
                "confirm": "11-999",
            },
        )

    assert response.status_code == 400
    assert "11-110" in response.json()["error"]["message"]


def test_apply_rejects_snapshot_outside_data_dir(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """경로를 데이터 디렉터리 안으로 가둔다."""
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)

    with _client() as client:
        response = client.post(
            "/api/dev/place-sync/apply",
            json={
                "snapshot": "../../etc/passwd",
                "detail_content_ids": [],
                "confirm": "11-110",
            },
        )

    assert response.status_code == 400


def test_reconcile_writes_snapshot_and_selects_detail_targets(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """대조는 목록 1회만 부르고 DB는 건드리지 않는다."""
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    baseline = {
        "1": _snapshot_row("1"),
        # 2번은 이번 목록에서 빠진다 → removed
        "2": _snapshot_row("2"),
        "3": _snapshot_row("3"),
    }
    place_snapshot.write_snapshot(
        baseline, tmp_path / f"{place_snapshot.SNAPSHOT_PREFIX}20260101.csv"
    )

    current = {
        # 1번은 좌표만 바뀜 → updated이지만 상세조회 제외
        "1": _snapshot_row("1", latitude="37.6"),
        # 3번은 수정시각이 바뀜 → 상세조회 대상
        "3": _snapshot_row("3", source_modified_at="2026-08-09T00:00:00+09:00"),
        # 4번은 신규 → 상세조회 대상
        "4": _snapshot_row("4"),
    }

    async def fake_fetch(client, api_key, area, district, fetched_at):
        return current

    monkeypatch.setattr(dev_routes.place_snapshot, "fetch_place_rows", fake_fetch)

    with _client() as client:
        payload = client.post("/api/dev/place-sync/reconcile", json={}).json()

    assert payload["counts"] == {"added": 1, "removed": 1, "updated": 2}
    assert payload["detail_content_ids"] == ["3", "4"]
    # 좌표만 바뀐 1번은 상세조회에서 빠지되, 조용히 사라지지 않고 드러나야 한다.
    assert payload["detail_excluded_ids"] == ["1"]
    assert (tmp_path / payload["snapshot"]).exists()
    assert (tmp_path / payload["reconciliation"]).exists()


def test_reconcile_reports_skipped_columns_from_old_baseline(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """옛 스냅샷에 없는 열은 비교하지 않는다는 사실을 화면이 알아야 한다."""
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    old_row = _snapshot_row("1")
    del old_row["first_image_url"]
    del old_row["thumbnail_url"]
    import csv as _csv

    baseline_path = tmp_path / f"{place_snapshot.SNAPSHOT_PREFIX}20260101.csv"
    with baseline_path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = _csv.DictWriter(fp, fieldnames=list(old_row))
        writer.writeheader()
        writer.writerow(old_row)

    async def fake_fetch(client, api_key, area, district, fetched_at):
        return {"1": _snapshot_row("1")}

    monkeypatch.setattr(dev_routes.place_snapshot, "fetch_place_rows", fake_fetch)

    with _client() as client:
        payload = client.post("/api/dev/place-sync/reconcile", json={}).json()

    assert set(payload["skipped_columns"]) == {"first_image_url", "thumbnail_url"}


def test_apply_runs_job_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    place_snapshot.write_snapshot(
        {"1": _snapshot_row("1")}, tmp_path / "places_api_snapshot_20260809.csv"
    )

    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def sync(self, area_code, district_code, **kwargs):
            captured.update(kwargs)
            kwargs["on_progress"](SyncProgress(phase="details", processed=1, total=1))
            return PlaceSyncResult(
                status="success",
                dry_run=kwargs["dry_run"],
                sync_run_id=None,
                api_total_count=1,
                processed_count=1,
                success_count=1,
                failed_count=0,
                new_count=0,
                updated_count=1,
                deactivated_count=0,
                detail_target_count=1,
                detail_attempted_count=1,
                reparse_count=0,
                error_summary={},
            )

    monkeypatch.setattr(dev_routes, "PlaceSyncService", _FakeService)

    async def fake_missing(self, content_ids):
        return list(content_ids)

    monkeypatch.setattr(
        dev_routes.SupabasePlaceRepository,
        "find_missing_concentration_mappings",
        fake_missing,
    )

    with _client() as client:
        started = client.post(
            "/api/dev/place-sync/apply",
            json={
                "snapshot": "places_api_snapshot_20260809.csv",
                "detail_content_ids": ["1"],
                "added_content_ids": ["1"],
                "dry_run": True,
                "confirm": "11-110",
            },
        ).json()
        job = client.get(f"/api/dev/place-sync/jobs/{started['job_id']}").json()

    assert captured["detail_content_ids"] == frozenset({"1"})
    assert captured["dry_run"] is True
    assert job["status"] == "success"
    assert (job["phase"], job["processed"], job["total"]) == ("details", 1, 1)
    assert job["result"]["detail_attempted_count"] == 1
    # 신규 장소는 집중률 매핑이 없다 — 이 동기화가 매핑 테이블을 갱신하지 않으므로
    # 알리지 않으면 그 장소만 조용히 혼잡도 판정에서 빠진다.
    assert job["unmapped_new_place_ids"] == ["1"]


def test_nearest_area_resolves_coordinate_to_area_name() -> None:
    """종로 한복판 좌표는 서울시 상권 지역 이름으로 근사된다."""

    with _client() as client:
        response = client.get("/api/dev/nearest-area", params={"location": "37.5709,126.9990"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["area_name"]
    assert payload["area_code"]
    # 근사치라는 사실을 숨기지 않으려고 거리를 함께 준다.
    assert payload["distance_km"] is not None
    assert payload["distance_km"] <= 2.0


def test_nearest_area_returns_empty_beyond_proxy_distance() -> None:
    """82개 지역에서 2km를 넘으면 빌려올 이름이 없다 — 임의의 상권으로 대체하지 않는다."""

    with _client() as client:
        response = client.get("/api/dev/nearest-area", params={"location": "35.1796,129.0756"})

    assert response.status_code == 200
    assert response.json() == {"area_code": None, "area_name": None, "distance_km": None}


def test_nearest_area_rejects_malformed_location() -> None:
    with _client() as client:
        response = client.get("/api/dev/nearest-area", params={"location": "종로3가"})

    assert response.status_code == 400
    # 원인을 화면에 그대로 띄우는 게 이 패널의 목적이라 공통 핸들러 문구로 덮이면 안 된다.
    assert "위도,경도" in response.json()["error"]["message"]
