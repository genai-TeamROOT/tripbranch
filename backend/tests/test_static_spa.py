# production 정적 배포(SPA fallback) 검증: frontend/dist가 있을 때 FastAPI 단독 실행이
# React Router 경로/실제 정적 파일/존재하지 않는 API 경로/문서 경로를 각각 올바르게 처리하는지 확인.
# 실제 frontend/dist를 빌드하지 않고, tmp_path에 최소 fixture(dist/index.html, dist/assets/app.js,
# dist/favicon.svg)를 만들어 app.core.static의 경로 상수를 monkeypatch한 뒤 앱을 새로 조립한다.

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.core.static as static_module
from app.main import create_app


@pytest.fixture
def built_frontend_client(tmp_path, monkeypatch) -> TestClient:
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)

    (dist_dir / "index.html").write_text("<html><body>SPA-ROOT</body></html>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('hello')", encoding="utf-8")
    (dist_dir / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")

    monkeypatch.setattr(static_module, "FRONTEND_DIST_DIR", dist_dir)
    monkeypatch.setattr(static_module, "INDEX_HTML_PATH", dist_dir / "index.html")
    monkeypatch.setattr(static_module, "ASSETS_DIR", assets_dir)

    return TestClient(create_app())


def test_root_serves_index_html(built_frontend_client: TestClient) -> None:
    response = built_frontend_client.get("/")

    assert response.status_code == 200
    assert "SPA-ROOT" in response.text


@pytest.mark.parametrize("path", ["/confirm", "/results"])
def test_react_router_paths_fall_back_to_index_html(
    built_frontend_client: TestClient, path: str
) -> None:
    response = built_frontend_client.get(path)

    assert response.status_code == 200
    assert "SPA-ROOT" in response.text


def test_hashed_asset_is_served_directly_not_index_html(built_frontend_client: TestClient) -> None:
    response = built_frontend_client.get("/assets/app.js")

    assert response.status_code == 200
    assert "console.log" in response.text


def test_top_level_static_file_is_served_directly(built_frontend_client: TestClient) -> None:
    response = built_frontend_client.get("/favicon.svg")

    assert response.status_code == 200
    assert "<svg" in response.text


def test_api_health_is_unaffected_by_spa_fallback(built_frontend_client: TestClient) -> None:
    response = built_frontend_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_api_path_does_not_fall_back_to_index_html(
    built_frontend_client: TestClient,
) -> None:
    response = built_frontend_client.get("/api/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "invalid_request"
    assert "SPA-ROOT" not in response.text


def test_docs_are_still_served(built_frontend_client: TestClient) -> None:
    response = built_frontend_client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_no_frontend_dist_means_no_op(client: TestClient) -> None:
    """The default `client` fixture (see conftest.py) points at the real
    app.main:app, where frontend/dist does not exist in this dev/test
    environment -- confirms mounting stays a no-op and the app still starts
    and serves the API normally."""
    response = client.get("/api/health")

    assert response.status_code == 200
