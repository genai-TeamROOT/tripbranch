"""무장애 후보 검색 RPC를 실제 Supabase로 확인하는 Smoke Test.

**여기서만 확인할 수 있는 것이 있다.** 원문을 읽어 "이 편의가 있다"를 가르는 판정은
`search_places_barrier_free` 함수 안에 있어, Fake로는 그 규칙이 도는지 알 수 없다.
특히 다음 한 줄이 이 파일의 존재 이유다.

    `없`·`미설치` 같은 단어로 부정을 판정하지 않는다.

접근로와 주출입구는 문장의 주어가 턱·단차라서 "없다"가 긍정이다. 단어로 거르면
894건을 잘못 버리고 4건을 맞게 버리는데(2026-09-01 실측), 그렇게 되어도 오류는
나지 않고 후보 수만 3분의 1로 줄어든다. 나중에 누가 "없음도 걸러야지" 하고 단어를
추가하면 여기서 걸린다.

실행:

    RUN_REAL_PROVIDER_TESTS=true python -m pytest -m smoke \\
        tests/test_barrier_free_search_rpc_smoke.py -v -s
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.config import Settings
from app.domain.models import AccessibilityNeed
from app.repositories.supabase_places import SupabasePlaceRepository

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv("RUN_REAL_PROVIDER_TESTS") != "true",
        reason="RUN_REAL_PROVIDER_TESTS=true일 때만 실제 Supabase를 호출합니다.",
    ),
]

settings = Settings()

# 안국역. 무장애 값이 채워진 장소가 반경 2km에 206곳으로 가장 많은 지점 중 하나다
# (2026-09-01 실측). 표본이 커야 판정이 뒤집혔을 때 눈에 띈다.
_ANGUK_LATITUDE = 37.5765
_ANGUK_LONGITUDE = 126.9857

# `출입구까지 턱이 없어 휠체어 접근 가능함`처럼 `없`이 긍정으로 쓰인 원문을 가진
# 장소다. 단어로 부정을 판정하면 이 장소들이 사라진다.
_WHEELCHAIR_EXPECTED_TITLES = {"대학로", "마로니에공원", "종묘광장공원"}

# `턱이 있어 접근 불가능한 구간 있음`. 명시적 불가라 빠져야 한다.
_EXPLICIT_BLOCKER_TITLE = "사직공원(서울)"


def _repository(client: httpx.AsyncClient) -> SupabasePlaceRepository:
    return SupabasePlaceRepository(
        supabase_url=settings.supabase_url,
        secret_key=settings.supabase_secret_key,
        client=client,
        timeout_seconds=settings.external_api_timeout_seconds,
    )


async def test_단차_없음_조건이_충분한_후보를_돌려준다() -> None:
    async with httpx.AsyncClient() as client:
        rows = await _repository(client).search_places_barrier_free(
            latitude=_ANGUK_LATITUDE,
            longitude=_ANGUK_LONGITUDE,
            radius_km=2.0,
            needs=(AccessibilityNeed.WHEELCHAIR_ACCESS,),
            limit=300,
        )

    print(f"\n안국역 2km · wheelchair_access: {len(rows)}곳")
    # 2026-09-01 실측 206곳. 적재가 늘 수 있어 하한만 본다 — 판정이 단어 매칭으로
    # 뒤집히면 100곳 아래로 떨어진다.
    assert len(rows) >= 150


async def test_없다는_말이_긍정인_원문을_버리지_않는다() -> None:
    """이 파일의 핵심. `턱이 없어 접근 가능함`이 후보로 남아야 한다."""
    async with httpx.AsyncClient() as client:
        rows = await _repository(client).search_places_barrier_free(
            latitude=_ANGUK_LATITUDE,
            longitude=_ANGUK_LONGITUDE,
            radius_km=3.0,
            needs=(AccessibilityNeed.WHEELCHAIR_ACCESS,),
            limit=500,
        )

    titles = {row.title for row in rows}
    missing = _WHEELCHAIR_EXPECTED_TITLES - titles
    assert not missing, (
        f"`없`이 긍정으로 쓰인 원문을 가진 장소가 빠졌습니다: {sorted(missing)}. "
        "판정에 단어 매칭이 들어갔는지 확인하세요."
    )


async def test_명시적_접근_불가는_빠진다() -> None:
    async with httpx.AsyncClient() as client:
        rows = await _repository(client).search_places_barrier_free(
            latitude=_ANGUK_LATITUDE,
            longitude=_ANGUK_LONGITUDE,
            radius_km=3.0,
            needs=(AccessibilityNeed.WHEELCHAIR_ACCESS,),
            limit=500,
        )

    assert _EXPLICIT_BLOCKER_TITLE not in {row.title for row in rows}


async def test_조건을_더하면_후보가_줄어든다() -> None:
    """여럿이면 전부 만족해야 한다(AND). OR이면 오히려 늘어난다."""
    async with httpx.AsyncClient() as client:
        repository = _repository(client)
        step_free_only = await repository.search_places_barrier_free(
            latitude=_ANGUK_LATITUDE,
            longitude=_ANGUK_LONGITUDE,
            radius_km=2.0,
            needs=(AccessibilityNeed.WHEELCHAIR_ACCESS,),
            limit=500,
        )
        with_restroom = await repository.search_places_barrier_free(
            latitude=_ANGUK_LATITUDE,
            longitude=_ANGUK_LONGITUDE,
            radius_km=2.0,
            needs=(
                AccessibilityNeed.WHEELCHAIR_ACCESS,
                AccessibilityNeed.ACCESSIBLE_RESTROOM,
            ),
            limit=500,
        )

    print(
        f"\nwheelchair_access 단독 {len(step_free_only)}곳 → "
        f"+accessible_restroom {len(with_restroom)}곳"
    )
    assert 0 < len(with_restroom) < len(step_free_only)
    assert {row.content_id for row in with_restroom} <= {
        row.content_id for row in step_free_only
    }


async def test_거리순으로_돌아온다() -> None:
    async with httpx.AsyncClient() as client:
        rows = await _repository(client).search_places_barrier_free(
            latitude=_ANGUK_LATITUDE,
            longitude=_ANGUK_LONGITUDE,
            radius_km=2.0,
            needs=(AccessibilityNeed.WHEELCHAIR_ACCESS,),
            limit=50,
        )

    distances = [row.distance_km for row in rows]
    assert distances == sorted(distances)
    assert all(distance <= 2.0 for distance in distances)


async def test_반경_밖은_돌아오지_않는다() -> None:
    """사각형 선걷어내기만 하고 하버사인을 빠뜨리면 모서리가 새어 나온다."""
    async with httpx.AsyncClient() as client:
        rows = await _repository(client).search_places_barrier_free(
            latitude=_ANGUK_LATITUDE,
            longitude=_ANGUK_LONGITUDE,
            radius_km=0.5,
            needs=(AccessibilityNeed.WHEELCHAIR_ACCESS,),
            limit=500,
        )

    assert all(row.distance_km <= 0.5 for row in rows)


async def test_빈_조건은_저장소에_닿기_전에_막힌다() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            await _repository(client).search_places_barrier_free(
                latitude=_ANGUK_LATITUDE,
                longitude=_ANGUK_LONGITUDE,
                radius_km=2.0,
                needs=(),
                limit=10,
            )


async def test_노인_동반_어휘가_다른_장소를_고른다() -> None:
    """의자식 테이블·저상버스는 단차 정보와 다른 컬럼을 읽는다.

    값 유무로 판정하면 안 되는 두 어휘라(의자식은 231행 중 142행, 저상버스는
    126행 중 99행) 문구 판정이 실제로 걸리는지 여기서 확인한다.
    """
    async with httpx.AsyncClient() as client:
        repository = _repository(client)
        seating = await repository.search_places_barrier_free(
            latitude=_ANGUK_LATITUDE, longitude=_ANGUK_LONGITUDE, radius_km=2.0,
            needs=(AccessibilityNeed.SEATING_AVAILABLE,), limit=500,
        )
        transit = await repository.search_places_barrier_free(
            latitude=_ANGUK_LATITUDE, longitude=_ANGUK_LONGITUDE, radius_km=2.0,
            needs=(AccessibilityNeed.LOW_FLOOR_TRANSIT,), limit=500,
        )

    print(f"\n의자식 테이블 {len(seating)}곳 · 저상버스 {len(transit)}곳")
    # 값 유무로 판정하면 각각 89곳·27곳이 더 들어온다. 그만큼 늘어나면 문구 판정이
    # 빠진 것이다.
    assert 0 < len(seating) < 60
    assert 0 < len(transit) < 50


async def test_휠체어와_유모차는_아직_같은_결과다() -> None:
    """판정이 붙으면 이 테스트가 깨지면서 두 값이 갈리기 시작했음을 알려준다."""
    async with httpx.AsyncClient() as client:
        repository = _repository(client)
        wheelchair = await repository.search_places_barrier_free(
            latitude=_ANGUK_LATITUDE, longitude=_ANGUK_LONGITUDE, radius_km=2.0,
            needs=(AccessibilityNeed.WHEELCHAIR_ACCESS,), limit=500,
        )
        stroller = await repository.search_places_barrier_free(
            latitude=_ANGUK_LATITUDE, longitude=_ANGUK_LONGITUDE, radius_km=2.0,
            needs=(AccessibilityNeed.STROLLER_ACCESS,), limit=500,
        )

    assert [r.content_id for r in wheelchair] == [r.content_id for r in stroller]

