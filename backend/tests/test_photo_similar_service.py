"""사진 검색 서비스의 위치 우선순위·하드 필터 연결·상한 처리 테스트."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.domain.models import PlaceMoodMatch, PlaceMoodProfile
from app.errors import AppError
from app.providers.contracts import ProviderSource, ProviderStatus, provider_result
from app.services import photo_similar
from app.services.photo_similar import PhotoSimilarQuery, build_photo_similar_places


@dataclass
class _Candidate:
    place_id: str
    name: str
    category: str = "카페"
    distance_km: float = 0.4


@dataclass
class _Prepared:
    place_ids: list[str]

    @property
    def preparation(self):
        rows = [
            type("Item", (), {"candidate": _Candidate(pid, f"장소 {pid}")})()
            for pid in self.place_ids
        ]
        return type("P", (), {"eligible_candidates": tuple(rows)})()


class _RecordingMood:
    """호출 인자만 기록하는 대역. SigLIP 없이 돈다."""

    def __init__(
        self,
        matches: tuple[PlaceMoodMatch, ...] = (),
        available: bool = True,
        photo_urls: dict[str, str] | None = None,
    ):
        self.calls: list[dict[str, object]] = []
        self.photo_url_calls: list[list[str]] = []
        self._matches = matches
        self._photo_urls = photo_urls or {}
        self.photo_search_available = available

    async def first_photo_urls(self, content_ids):
        self.photo_url_calls.append(list(content_ids))
        return dict(self._photo_urls)

    async def search_by_photo(self, image_bytes, candidate_content_ids=None):
        self.calls.append(
            {
                "bytes": len(image_bytes),
                "candidates": list(candidate_content_ids or []),
            }
        )
        return provider_result(
            self._matches,
            source=ProviderSource.SUPABASE_PLACE_MOOD,
            status=ProviderStatus.SUCCESS if self._matches else ProviderStatus.NO_DATA,
        )


def _match(content_id: str, similarity: float) -> PlaceMoodMatch:
    return PlaceMoodMatch(
        content_id=content_id,
        similarity=similarity,
        profile=PlaceMoodProfile(
            content_id=content_id, axis_scores={"calm": 0.02}, photo_count=4
        ),
    )


@pytest.fixture
def patched(monkeypatch):
    """위치·장소·하드 필터를 대역으로 바꿔 외부 호출 없이 흐름만 본다."""
    seen: dict[str, object] = {}

    class _Tool:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, query):
            seen["nearby"] = query
            return type("R", (), {"status": None, "places": []})()

    async def _fake_prepare(context, **kwargs):
        seen["prepare_kwargs"] = kwargs
        return _Prepared(seen.get("place_ids", ["a", "b", "c"]))

    monkeypatch.setattr(photo_similar, "NearbyPlaceDetailsTool", _Tool)
    monkeypatch.setattr(photo_similar, "map_places_context", lambda r: None)
    monkeypatch.setattr(photo_similar, "map_location_context", lambda r: None)
    monkeypatch.setattr(photo_similar, "prepare_recommendation_from_context", _fake_prepare)
    return seen


@pytest.mark.asyncio
async def test_gps_is_used_when_no_location_query(patched) -> None:
    """지역명이 없으면 좌표를 그대로 쓴다 — 지오코딩을 타지 않는다."""
    mood = _RecordingMood(matches=(_match("a", 0.9),))

    result = await build_photo_similar_places(
        PhotoSimilarQuery(image_bytes=b"jpeg", latitude=37.57, longitude=126.98),
        geocoding_provider=object(),
        place_provider=object(),
        mood_provider=mood,
    )

    assert result.center_latitude == pytest.approx(37.57)
    assert result.center_name == "기기 GPS 위치"
    assert mood.calls[0]["candidates"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_missing_location_asks_again(patched) -> None:
    """지역명도 좌표도 없으면 되묻는다. 임의로 어딘가를 고르지 않는다."""
    with pytest.raises(AppError) as error:
        await build_photo_similar_places(
            PhotoSimilarQuery(image_bytes=b"jpeg"),
            geocoding_provider=object(),
            place_provider=object(),
            mood_provider=_RecordingMood(),
        )

    assert error.value.code == "location_required"


@pytest.mark.asyncio
async def test_encoder_absent_is_an_error_not_empty_result(patched) -> None:
    """기능이 꺼진 것과 "닮은 곳이 없다"는 다르다.

    조용히 빈 목록을 주면 왜 안 나오는지 추적할 수 없다(D-042와 같은 이유).
    """
    with pytest.raises(AppError) as error:
        await build_photo_similar_places(
            PhotoSimilarQuery(image_bytes=b"jpeg", latitude=37.5, longitude=127.0),
            geocoding_provider=object(),
            place_provider=object(),
            mood_provider=_RecordingMood(available=False),
        )

    assert error.value.code == "photo_search_unavailable"


@pytest.mark.asyncio
async def test_empty_image_is_rejected(patched) -> None:
    with pytest.raises(AppError) as error:
        await build_photo_similar_places(
            PhotoSimilarQuery(image_bytes=b"", latitude=37.5, longitude=127.0),
            geocoding_provider=object(),
            place_provider=object(),
            mood_provider=_RecordingMood(),
        )

    assert error.value.code == "empty_image"


@pytest.mark.asyncio
async def test_candidates_are_capped_at_the_rpc_limit(patched) -> None:
    """500건을 넘기면 RPC가 에러를 낸다. 앞에서 잘라 넘기고 몇 건 잘렸는지 알린다."""
    patched["place_ids"] = [str(i) for i in range(620)]
    mood = _RecordingMood()

    result = await build_photo_similar_places(
        PhotoSimilarQuery(image_bytes=b"jpeg", latitude=37.5, longitude=127.0),
        geocoding_provider=object(),
        place_provider=object(),
        mood_provider=mood,
    )

    assert len(mood.calls[0]["candidates"]) == 500
    assert result.candidate_count == 500
    assert result.truncated_count == 120


@pytest.mark.asyncio
async def test_result_carries_candidate_name_without_extra_lookup(patched) -> None:
    """장소명은 후보에서 가져온다 — 상세를 다시 조회하지 않는다."""
    mood = _RecordingMood(matches=(_match("b", 0.88), _match("a", 0.81)))

    result = await build_photo_similar_places(
        PhotoSimilarQuery(image_bytes=b"jpeg", latitude=37.5, longitude=127.0),
        geocoding_provider=object(),
        place_provider=object(),
        mood_provider=mood,
    )

    assert [row.name for row in result.places] == ["장소 b", "장소 a"]
    assert result.places[0].similarity == pytest.approx(0.88)
    assert result.places[0].photo_count == 4


@pytest.mark.asyncio
async def test_unknown_content_id_is_skipped(patched) -> None:
    """후보에 없는 content_id가 오면 이름 없는 카드를 내보내지 않고 건너뛴다."""
    mood = _RecordingMood(matches=(_match("zzz", 0.9), _match("a", 0.8)))

    result = await build_photo_similar_places(
        PhotoSimilarQuery(image_bytes=b"jpeg", latitude=37.5, longitude=127.0),
        geocoding_provider=object(),
        place_provider=object(),
        mood_provider=mood,
    )

    assert [row.content_id for row in result.places] == ["a"]


@pytest.mark.asyncio
async def test_limit_is_applied(patched) -> None:
    mood = _RecordingMood(
        matches=(_match("a", 0.9), _match("b", 0.8), _match("c", 0.7))
    )

    result = await build_photo_similar_places(
        PhotoSimilarQuery(image_bytes=b"x", latitude=37.5, longitude=127.0, limit=2),
        geocoding_provider=object(),
        place_provider=object(),
        mood_provider=mood,
    )

    assert len(result.places) == 2


@pytest.mark.asyncio
async def test_first_photo_url_is_attached(patched) -> None:
    """비교에 쓴 사진을 결과에 싣는다.

    places.first_image_url이 아니다 — 2,008곳 중 1,163곳이 서로 다른 주소라
    (2026-08-27 실측) 대표 이미지를 보여주면 비교하지 않은 사진을 보여주게 된다.
    """
    mood = _RecordingMood(
        matches=(_match("a", 0.9),),
        photo_urls={"a": "https://tong.visitkorea.or.kr/x.jpg"},
    )

    result = await build_photo_similar_places(
        PhotoSimilarQuery(image_bytes=b"jpeg", latitude=37.5, longitude=127.0),
        geocoding_provider=object(),
        place_provider=object(),
        mood_provider=mood,
    )

    assert result.places[0].image_url == "https://tong.visitkorea.or.kr/x.jpg"


@pytest.mark.asyncio
async def test_photo_urls_are_fetched_only_for_shown_places(patched) -> None:
    """후보 전체가 아니라 보여줄 만큼만 조회한다."""
    mood = _RecordingMood(
        matches=(_match("a", 0.9), _match("b", 0.8), _match("c", 0.7))
    )

    await build_photo_similar_places(
        PhotoSimilarQuery(image_bytes=b"x", latitude=37.5, longitude=127.0, limit=2),
        geocoding_provider=object(),
        place_provider=object(),
        mood_provider=mood,
    )

    assert mood.photo_url_calls == [["a", "b"]]


@pytest.mark.asyncio
async def test_missing_photo_url_is_not_an_error(patched) -> None:
    """사진이 안 보이는 것과 결과가 안 나오는 것은 무게가 다르다."""
    mood = _RecordingMood(matches=(_match("a", 0.9),), photo_urls={})

    result = await build_photo_similar_places(
        PhotoSimilarQuery(image_bytes=b"x", latitude=37.5, longitude=127.0),
        geocoding_provider=object(),
        place_provider=object(),
        mood_provider=mood,
    )

    assert result.places[0].image_url is None
    assert result.places[0].name == "장소 a"
