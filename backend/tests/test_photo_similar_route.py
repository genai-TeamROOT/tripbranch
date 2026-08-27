"""사진 검색 라우트의 입력 검증과 응답 조립 테스트."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import photo_similar as route
from app.services.photo_similar import PhotoSimilarPlaceRow, PhotoSimilarResult

_URL = "/api/places/similar-by-photo"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _image(name: str = "a.jpg", mime: str = "image/jpeg", data: bytes = b"\xff\xd8fake"):
    return {"image": (name, io.BytesIO(data), mime)}


def test_unsupported_format_is_rejected(client) -> None:
    response = client.post(
        _URL, files={"image": ("a.gif", io.BytesIO(b"GIF8"), "image/gif")},
        data={"latitude": "37.5", "longitude": "127.0"},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_image_format"


def test_empty_image_is_rejected(client) -> None:
    response = client.post(
        _URL, files={"image": ("a.jpg", io.BytesIO(b""), "image/jpeg")},
        data={"latitude": "37.5", "longitude": "127.0"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_image"


def test_oversized_image_is_rejected(client, monkeypatch) -> None:
    monkeypatch.setattr(route, "_MAX_IMAGE_BYTES", 8)
    response = client.post(
        _URL, files=_image(data=b"0123456789"),
        data={"latitude": "37.5", "longitude": "127.0"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_large"


def test_successful_response_shape(client, monkeypatch) -> None:
    async def _fake(query, **kwargs):
        assert query.image_bytes
        assert query.latitude == pytest.approx(37.5)
        return PhotoSimilarResult(
            places=(
                PhotoSimilarPlaceRow("2946087", "마우스래빗", "카페", 0.4, 0.89, 6),
            ),
            center_name="기기 GPS 위치",
            center_latitude=37.5,
            center_longitude=127.0,
            candidate_count=42,
            truncated_count=0,
        )

    monkeypatch.setattr(route, "build_photo_similar_places", _fake)
    response = client.post(
        _URL, files=_image(), data={"latitude": "37.5", "longitude": "127.0"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["center_name"] == "기기 GPS 위치"
    assert body["candidate_count"] == 42
    assert body["places"][0]["title"] == "마우스래빗"
    assert body["places"][0]["photo_count"] == 6
    assert body["elapsed_ms"] >= 0


def test_limit_is_clamped(client, monkeypatch) -> None:
    """상한을 넘겨도 응답만 커지고 얻는 게 없다. 조용히 자른다."""
    seen: dict[str, int] = {}

    async def _fake(query, **kwargs):
        seen["limit"] = query.limit
        return PhotoSimilarResult((), "여기", 0.0, 0.0, 0, 0)

    monkeypatch.setattr(route, "build_photo_similar_places", _fake)
    client.post(
        _URL, files=_image(),
        data={"latitude": "37.5", "longitude": "127.0", "limit": "999"},
    )
    assert seen["limit"] == route._MAX_LIMIT


def test_blank_location_query_falls_back_to_gps(client, monkeypatch) -> None:
    """공백만 든 지역명은 안 적은 것과 같게 다룬다."""
    seen: dict[str, object] = {}

    async def _fake(query, **kwargs):
        seen["location_query"] = query.location_query
        return PhotoSimilarResult((), "여기", 0.0, 0.0, 0, 0)

    monkeypatch.setattr(route, "build_photo_similar_places", _fake)
    client.post(
        _URL, files=_image(),
        data={"latitude": "37.5", "longitude": "127.0", "location_query": "   "},
    )
    assert seen["location_query"] is None
