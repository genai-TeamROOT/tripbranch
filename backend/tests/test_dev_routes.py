"""개발자 Ops 패널 API(/api/dev/*) 테스트."""

from __future__ import annotations

from datetime import datetime

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


def test_db_status_splits_places_by_district_and_keeps_history_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """장소 요약은 구별로 나누고, 동기화 이력·잠금은 전 구 목록 그대로 준다."""
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
                        "district_code": "170",
                        "is_active": False,
                        "detail_fetch_status": "pending",
                        "operating_parse_status": "unknown",
                        "operating_parser_version": "operating-hours-1.0.0",
                        "detail_fetched_at": None,
                    },
                ],
            )
        if path.endswith("/place_sync_runs"):
            return httpx.Response(
                200,
                json=[{"id": "run-1", "district_code": "170", "status": "success"}],
            )
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

    assert payload["overall"]["total"] == 2
    assert payload["overall"]["active"] == 1
    # 이름은 코드에 박지 않고 tour_api_ldong_codes.json에서 찾아 붙인다.
    assert [(d["district_code"], d["district_name"]) for d in payload["districts"]] == [
        ("110", "종로구"),
        ("170", "용산구"),
    ]
    assert payload["districts"][0]["total"] == 1
    assert payload["districts"][1]["inactive"] == 1
    # 이력과 잠금은 구로 나누지 않는다 — 화면에서도 탭 밖에 둔다.
    assert payload["sync_runs"] == [
        {"id": "run-1", "district_code": "170", "status": "success"}
    ]
    assert payload["sync_locks"] == []
    assert payload["place_enrichments_count"] == 12
    assert payload["place_concentration_mappings_count"] == 12
    assert payload["detail_ttl_days"] == settings.place_sync_detail_ttl_days
    # 오늘 상세조회 사용량은 place_sync_runs에서 센다. 메모리 집계와 달리 서버를
    # 재시작해도 남고 스크립트 실행분도 잡히지만, 값이 없는 실행은 따로 알린다.
    assert payload["detail_calls_today"] == {
        "count": 0,
        "runs": 1,
        "runs_without_count": 1,
        "daily_limit": settings.tour_api_daily_call_limit,
    }


def test_db_status_names_unknown_district_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """자료에 없는 코드가 와도 조회 전체가 실패하지 않는다 — 이름만 비운다."""
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Range": "*/0"})
        if request.url.path.endswith("/places"):
            return httpx.Response(
                200,
                json=[{"area_code": "11", "district_code": "999", "is_active": True}],
            )
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        dev_routes,
        "status_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with _client() as client:
        payload = client.get("/api/dev/db-status").json()

    assert payload["districts"][0]["district_name"] is None
    assert payload["districts"][0]["district_code"] == "999"


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


def _mock_no_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    """상세 정보를 못 채운 장소가 없는 DB. 대조가 그것도 세기 때문에 필요하다."""
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")
    monkeypatch.setattr(
        dev_routes,
        "status_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
        ),
    )


def _baseline_name(area_code: str = "11", district_code: str = "110") -> str:
    """테스트용 기준 스냅샷 파일명. 구가 들어간 현재 규칙을 따른다."""
    return place_snapshot.snapshot_file_name(
        area_code, district_code, datetime(2026, 1, 1, tzinfo=place_snapshot.KST)
    )


def test_reconcile_writes_snapshot_and_selects_detail_targets(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """대조는 목록 1회만 부르고 DB는 건드리지 않는다."""
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    _mock_no_backfill(monkeypatch)
    baseline = {
        "1": _snapshot_row("1"),
        # 2번은 이번 목록에서 빠진다 → removed
        "2": _snapshot_row("2"),
        "3": _snapshot_row("3"),
    }
    place_snapshot.write_snapshot(baseline, tmp_path / _baseline_name())

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
    # 파일명에 구가 없으면 같은 날 다른 구를 대조할 때 서로를 덮어쓴다.
    assert payload["snapshot"].startswith("places_api_snapshot_11-110_")
    assert payload["reconciliation"].startswith("places_reconciliation_11-110_")
    assert payload["baseline"] == _baseline_name()


def test_reconcile_reports_skipped_columns_from_old_baseline(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """옛 스냅샷에 없는 열은 비교하지 않는다는 사실을 화면이 알아야 한다."""
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    _mock_no_backfill(monkeypatch)
    old_row = _snapshot_row("1")
    del old_row["first_image_url"]
    del old_row["thumbnail_url"]
    import csv as _csv

    baseline_path = tmp_path / _baseline_name()
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


def test_apply_rejects_snapshot_from_another_district(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """다른 구 스냅샷으로 반영하면 대상 구의 활성 장소가 전부 비활성화된다.

    스냅샷에 없는 장소는 "목록에서 사라진 것"으로 판정돼
    `deactivate_unseen_places`가 끄는데, 중구 스냅샷에는 종로구 장소가 하나도
    없으므로 종로구 전량이 대상이 된다. 실행 전에 막는다.
    """
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    place_snapshot.write_snapshot(
        {"1": _snapshot_row("1", district_code="140")},
        tmp_path / place_snapshot.snapshot_file_name(
            "11", "140", datetime(2026, 8, 20, tzinfo=place_snapshot.KST)
        ),
    )

    with _client() as client:
        response = client.post(
            "/api/dev/place-sync/apply",
            json={
                "snapshot": "places_api_snapshot_11-140_20260820.csv",
                "detail_content_ids": ["1"],
                "confirm": "11-110",
            },
        )

    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "11-140" in message and "11-110" in message


def test_reconcile_ignores_other_district_snapshot_as_baseline(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """다른 구 스냅샷은 기준으로 잡히지 않는다.

    잡히면 "전량 삭제 + 전량 신규"가 나오는데, 그 모양은 실제 대량 변경과
    구분되지 않는다. 2026-08-20에 중구를 종로구 스냅샷과 대조해 "삭제 844건"이
    나온 사고가 그것이다.
    """
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")
    # DB에도 종로구 장소가 없는 상태로 둔다. 여기서 보려는 것은 파일 선택이다.
    monkeypatch.setattr(
        dev_routes,
        "status_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
        ),
    )
    place_snapshot.write_snapshot(
        {"9": _snapshot_row("9", district_code="140")},
        tmp_path / place_snapshot.snapshot_file_name(
            "11", "140", datetime(2026, 8, 20, tzinfo=place_snapshot.KST)
        ),
    )

    async def fake_fetch(client, api_key, area, district, fetched_at):
        return {"1": _snapshot_row("1")}

    monkeypatch.setattr(dev_routes.place_snapshot, "fetch_place_rows", fake_fetch)

    with _client() as client:
        payload = client.post("/api/dev/place-sync/reconcile", json={}).json()

    # 종로구 기준이 없으니 "기준 없음"이지, 중구 것을 끌어다 쓰지 않는다.
    assert payload["baseline"] is None
    assert payload["counts"] == {"added": 0, "removed": 0, "updated": 0}
    assert payload["baseline_source"] == "none"


def test_reconcile_builds_baseline_from_database_when_no_snapshot(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """스냅샷이 없어도 DB에 장소가 있으면 그것으로 기준을 세운다.

    없으면 전량이 신규로 잡혀, 이미 DB에 있는 장소에 detailIntro2를 한 번씩 더
    쓴다. 용산구 486건이면 하루 한도 1,000회의 절반이다.
    """
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["district_code"] == "eq.110"
        # 1번은 DB에 있고, 2번은 이번 목록에만 있다 → 신규 1건.
        return httpx.Response(200, json=[_snapshot_row("1")])

    monkeypatch.setattr(
        dev_routes,
        "status_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async def fake_fetch(client, api_key, area, district, fetched_at):
        return {"1": _snapshot_row("1"), "2": _snapshot_row("2")}

    monkeypatch.setattr(dev_routes.place_snapshot, "fetch_place_rows", fake_fetch)

    with _client() as client:
        payload = client.post("/api/dev/place-sync/reconcile", json={}).json()

    assert payload["baseline_source"] == "database"
    # 기준을 파일로 남기지 않는다 — 오늘 날짜 파일과 이름이 겹쳐 덮어써진다.
    assert payload["baseline"].startswith("places@")
    assert payload["counts"] == {"added": 1, "removed": 0, "updated": 0}
    assert payload["detail_content_ids"] == ["2"]


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


@pytest.mark.asyncio
async def test_database_baseline_reports_unavailable_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """자격증명이 없으면 "DB에 없다"가 아니라 "확인하지 못했다"로 돌려준다.

    두 가지를 같은 결과로 뭉개면, 낭비된 상세조회를 두고 화면이 "원래 없던
    구"인지 "못 본 것"인지 설명할 수 없다.

    (앱 기동은 이 상태를 애초에 막지만 — PLACE_DETAILS_SOURCE=supabase면
    validate_provider_config가 거부한다 — 다른 details source에서는 자격증명 없이도
    패널이 뜬다.)
    """
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_secret_key", "")

    baseline, source = await dev_routes._baseline_from_database("11", "110")

    assert baseline == {}
    assert source == "unavailable"


def test_sync_districts_lists_loaded_and_known(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """자료가 있는 구와, 구 추가 입력을 검증할 사전을 함께 준다."""
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    # 대조만 하고 아직 반영하지 않은 구. 파일만 있어도 목록에 남아야 한다.
    place_snapshot.write_snapshot(
        {"9": _snapshot_row("9", district_code="200")},
        tmp_path / place_snapshot.snapshot_file_name(
            "11", "200", datetime(2026, 8, 21, tzinfo=place_snapshot.KST)
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"area_code": "11", "district_code": "110", "is_active": True},
                {"area_code": "11", "district_code": "110", "is_active": False},
            ],
        )

    monkeypatch.setattr(
        dev_routes,
        "status_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with _client() as client:
        payload = client.get("/api/dev/place-sync/districts").json()

    loaded = {row["district_code"]: row for row in payload["loaded"]}
    assert loaded["110"]["place_count"] == 2
    assert loaded["110"]["active_count"] == 1
    assert loaded["110"]["district_name"] == "종로구"
    # 대조 한 번이 쓰는 목록 호출 수. 1,000건마다 1회다.
    assert loaded["110"]["list_call_estimate"] == 1
    # DB에는 없고 스냅샷만 있는 구도 선택지에 남는다.
    assert loaded["200"]["place_count"] == 0
    assert loaded["200"]["latest_snapshot"] == (
        "places_api_snapshot_11-200_20260821.csv"
    )
    # 사전은 서울 25개 구 전체다 — 없는 코드 입력을 화면이 막는 근거다.
    assert len(payload["known"]) == 25
    assert {"area_code": "11", "district_code": "170", "district_name": "용산구"} in (
        payload["known"]
    )


def test_apply_passes_details_limit_to_service(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """상한이 서비스까지 가야 한다. 안 가면 화면만 나눠 받은 척한다."""
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    place_snapshot.write_snapshot(
        {"1": _snapshot_row("1")},
        tmp_path / place_snapshot.snapshot_file_name(
            "11", "110", datetime(2026, 8, 21, tzinfo=place_snapshot.KST)
        ),
    )
    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def sync(self, area_code, district_code, **kwargs):
            captured.update(kwargs)
            return PlaceSyncResult(
                status="success",
                dry_run=True,
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
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")

    with _client() as client:
        started = client.post(
            "/api/dev/place-sync/apply",
            json={
                "snapshot": "places_api_snapshot_11-110_20260821.csv",
                "detail_content_ids": ["1"],
                "dry_run": True,
                "details_limit": 300,
                "confirm": "11-110",
            },
        ).json()
        for _ in range(50):
            job = client.get(f"/api/dev/place-sync/jobs/{started['job_id']}").json()
            if job["status"] != "running":
                break

    assert captured["details_limit"] == 300
    assert job["params"]["details_limit"] == 300


def test_apply_rejects_details_limit_below_one(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    place_snapshot.write_snapshot(
        {"1": _snapshot_row("1")},
        tmp_path / place_snapshot.snapshot_file_name(
            "11", "110", datetime(2026, 8, 21, tzinfo=place_snapshot.KST)
        ),
    )

    with _client() as client:
        response = client.post(
            "/api/dev/place-sync/apply",
            json={
                "snapshot": "places_api_snapshot_11-110_20260821.csv",
                "detail_content_ids": ["1"],
                "details_limit": 0,
                "confirm": "11-110",
            },
        )

    assert response.status_code == 422


def test_reconcile_counts_places_missing_details_as_extra_calls(
    monkeypatch: pytest.MonkeyPatch, _real_place: None, tmp_path
) -> None:
    """반영은 변경분과 **함께** pending·failed 장소도 부른다. 그 수를 대조가 알려야 한다.

    2026-08-21 종로구 대조가 이 상태였다. 화면은 "상세조회 15회"라고 표시했지만
    실제 반영은 못 채운 142건을 더해 157회를 썼을 것이다. 한도가 왜 줄었는지
    설명할 수 없는 숫자가 된다.
    """
    monkeypatch.setattr(dev_routes.place_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")
    place_snapshot.write_snapshot(
        {"1": _snapshot_row("1"), "2": _snapshot_row("2"), "3": _snapshot_row("3")},
        tmp_path / _baseline_name(),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["detail_fetch_status"] == "in.(pending,failed)"
        return httpx.Response(
            200,
            json=[
                # 2번은 이번 변경분에도 들어 있다 — 두 번 세면 안 된다.
                {"content_id": "2"},
                {"content_id": "3"},
                # 9번은 이번 목록에 없다(비활성). 동기화가 훑지 않으므로 제외한다.
                {"content_id": "9"},
            ],
        )

    monkeypatch.setattr(
        dev_routes,
        "status_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async def fake_fetch(client, api_key, area, district, fetched_at):
        return {
            "1": _snapshot_row("1"),
            "2": _snapshot_row("2", source_modified_at="2026-08-21T00:00:00+09:00"),
            "3": _snapshot_row("3"),
        }

    monkeypatch.setattr(dev_routes.place_snapshot, "fetch_place_rows", fake_fetch)

    with _client() as client:
        payload = client.post("/api/dev/place-sync/reconcile", json={}).json()

    assert payload["detail_content_ids"] == ["2"]
    assert payload["detail_backfill_ids"] == ["3"]
    assert payload["detail_backfill_checked"] is True


@pytest.mark.asyncio
async def test_detail_backfill_reports_unchecked_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """못 본 것과 "보충할 게 없다"를 0으로 뭉개면 예상 호출수가 확정값처럼 보인다."""
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_secret_key", "")

    ids, checked = await dev_routes._detail_backfill_ids(
        "11", "110", {"1": _snapshot_row("1")}, frozenset()
    )

    assert ids == []
    assert checked is False


def test_list_call_estimate_counts_one_call_per_thousand_places() -> None:
    """areaBasedList2도 일일 한도가 있다(2026-08-07 소진). 쪽수만큼 호출이 늘어난다."""
    assert dev_routes._list_call_estimate(0) == 1
    assert dev_routes._list_call_estimate(883) == 1
    assert dev_routes._list_call_estimate(1000) == 1
    assert dev_routes._list_call_estimate(1001) == 2
