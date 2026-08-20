from app.services.runtime.info_display import (
    format_citydata_timestamp,
    format_parking_for_display,
)


def test_format_parking_for_display_keeps_only_car_capacity() -> None:
    assert format_parking_for_display("가능 (승용차 240대 / 버스 50대)") == "가능 (승용차 240대)"


def test_format_parking_for_display_keeps_unknown_shape_unchanged() -> None:
    assert format_parking_for_display("가능") == "가능"


def test_format_citydata_timestamp_normalizes_compact_and_iso_shapes() -> None:
    assert format_citydata_timestamp("20260820 1520") == "8월 20일 15:20"
    assert format_citydata_timestamp("2026-08-20 15:20") == "8월 20일 15:20"
