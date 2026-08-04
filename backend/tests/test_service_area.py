"""지원 지역(서울 종로구) 좌표 판정을 고정한다.

경계 상자로는 갈리지 않던 지점이 있어 폴리곤을 쓴다 — 종로구는 남북으로 길쭉하고
북악산 쪽으로 굽어 있어, 상자에 여유를 주면 중구 명동·서울역이 안쪽으로 들어온다.
"""

from __future__ import annotations

import pytest

from app.service_area import is_within_service_area

# 실제 좌표. 경계 판정이 흔들리면 바로 드러나도록 경계 인접 지점을 함께 둔다.
_INSIDE = {
    "경복궁": (37.5760, 126.9767),
    "북촌한옥마을": (37.5826, 126.9850),
    "창덕궁": (37.5794, 126.9910),
    "부암동": (37.5972, 126.9663),
    "내자상회": (37.5756, 126.9722),
}
_OUTSIDE = {
    "망원역": (37.556068, 126.9101053),
    "홍대입구역": (37.5568, 126.9236),
    "강남역": (37.4979, 127.0276),
    # 중구다. 종로구 남쪽 경계에 가까워 상자로는 걸러지지 않았다.
    "명동": (37.5636, 126.9827),
    "서울역": (37.5547, 126.9707),
    "부산역": (35.1151, 129.0415),
}


@pytest.mark.parametrize(("name", "point"), _INSIDE.items())
def test_지원_지역_안(name: str, point: tuple[float, float]) -> None:
    assert is_within_service_area(*point), name


@pytest.mark.parametrize(("name", "point"), _OUTSIDE.items())
def test_지원_지역_밖(name: str, point: tuple[float, float]) -> None:
    assert not is_within_service_area(*point), name


def test_경계_데이터는_한_번만_읽는다() -> None:
    """정적 데이터라 요청마다 파일을 열지 않는다."""
    from app.service_area import _service_area_polygons

    first = _service_area_polygons()
    assert _service_area_polygons() is first
