"""위치 설정 화면의 장소 검색 라우트 테스트."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.models import LocalSearchPlace
from app.main import app
from app.providers.contracts import ProviderSource, provider_result
from app.routes import place_search as route

_URL = "/api/places/search"

# 안국역(종로구). service_area의 서울 경계 안이다.
_SEOUL_LATITUDE = 37.5765389
_SEOUL_LONGITUDE = 126.9856
# 해운대(부산). 지원 지역 밖이다.
_BUSAN_LATITUDE = 35.1587
_BUSAN_LONGITUDE = 129.1604


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class _FakeProvider:
    """검색어와 display를 그대로 기록해 두는 지역 검색 대역."""

    def __init__(self, places: tuple[LocalSearchPlace, ...]) -> None:
        self._places = places
        self.received_query: str | None = None
        self.received_display: int | None = None

    async def search_places_by_name(self, query: str, *, display: int = 5):
        self.received_query = query
        self.received_display = display
        return provider_result(self._places, source=ProviderSource.FAKE_LOCAL_SEARCH)


def _install(monkeypatch, *places: LocalSearchPlace) -> _FakeProvider:
    provider = _FakeProvider(places)
    monkeypatch.setattr(route, "get_local_search_provider", lambda client: provider)
    return provider


def _place(name: str, latitude: float | None, longitude: float | None) -> LocalSearchPlace:
    return LocalSearchPlace(
        name=name,
        address=f"{name} 지번주소",
        road_address=f"{name} 도로명주소",
        category="지하철,전철",
        latitude=latitude,
        longitude=longitude,
    )


def test_seoul_place_is_returned_with_name_and_coordinates(client, monkeypatch) -> None:
    _install(monkeypatch, _place("안국역", _SEOUL_LATITUDE, _SEOUL_LONGITUDE))

    response = client.get(_URL, params={"query": "안국역"})

    assert response.status_code == 200
    body = response.json()
    assert body["outside_service_area_count"] == 0
    assert [place["name"] for place in body["places"]] == ["안국역"]
    assert body["places"][0]["road_address"] == "안국역 도로명주소"
    assert body["places"][0]["latitude"] == pytest.approx(_SEOUL_LATITUDE)


def test_place_outside_seoul_is_dropped_and_counted(client, monkeypatch) -> None:
    """서울 밖은 후보에서 빼되 개수를 남긴다 — 화면이 이유를 말해야 한다."""
    _install(
        monkeypatch,
        _place("서울역", _SEOUL_LATITUDE, _SEOUL_LONGITUDE),
        _place("해운대역", _BUSAN_LATITUDE, _BUSAN_LONGITUDE),
    )

    body = client.get(_URL, params={"query": "역"}).json()

    assert [place["name"] for place in body["places"]] == ["서울역"]
    assert body["outside_service_area_count"] == 1


def test_place_without_coordinates_is_dropped_without_counting(client, monkeypatch) -> None:
    """좌표 없는 후보는 검색 위치로 쓸 수 없지만 서울 밖이라 뺀 것은 아니다."""
    _install(monkeypatch, _place("좌표없는곳", None, None))

    body = client.get(_URL, params={"query": "좌표없는곳"}).json()

    assert body["places"] == []
    assert body["outside_service_area_count"] == 0


def test_query_is_scoped_to_seoul_before_calling_provider(client, monkeypatch) -> None:
    """지역 검색은 전국 5건뿐이라 서울을 붙이지 않으면 지방 결과에 밀린다."""
    provider = _install(monkeypatch, _place("중앙동", _SEOUL_LATITUDE, _SEOUL_LONGITUDE))

    client.get(_URL, params={"query": "중앙동 카페"})

    assert provider.received_query == "서울 중앙동 카페"
    assert provider.received_display == 5


@pytest.mark.parametrize("query", ["서울 중앙동", "종로구 카페", "강남구청역"])
def test_query_already_pointing_at_seoul_is_left_alone(query: str) -> None:
    assert route.seoul_scoped_query(query) == query


def test_blank_query_is_rejected_before_calling_provider(client, monkeypatch) -> None:
    """공백만 보내면 외부 API를 부르지 않고 끊는다."""
    provider = _install(monkeypatch)

    response = client.get(_URL, params={"query": "  "})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert provider.received_query is None


def test_missing_query_is_rejected(client) -> None:
    assert client.get(_URL).status_code == 422
