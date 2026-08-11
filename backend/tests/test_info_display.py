from app.services.runtime.info_display import format_parking_for_display


def test_format_parking_for_display_keeps_only_car_capacity() -> None:
    assert format_parking_for_display("가능 (승용차 240대 / 버스 50대)") == "가능 (승용차 240대)"


def test_format_parking_for_display_keeps_unknown_shape_unchanged() -> None:
    assert format_parking_for_display("가능") == "가능"
