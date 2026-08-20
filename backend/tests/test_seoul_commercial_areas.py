"""서울시 실시간 상권 제공 지역 선택 규칙 회귀 테스트."""

from app.agent_context.seoul_commercial_areas import select_nearest_commercial_area


def test_yongridan_gil_coordinate_selects_yongridan_gil() -> None:
    selected = select_nearest_commercial_area(latitude=37.5311, longitude=126.9715)

    assert selected is not None
    area, distance_km = selected
    assert area.code == "POI076"
    assert area.name == "용리단길"
    assert distance_km == 0.0


def test_outside_official_commercial_coverage_returns_none() -> None:
    # 부산 좌표는 서울시 주요 상권의 최근접 대체 범위 밖이다.
    selected = select_nearest_commercial_area(latitude=35.1796, longitude=129.0756)

    assert selected is None
