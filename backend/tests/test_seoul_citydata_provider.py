"""서울시 실시간 상권현황 Provider의 응답 정규화를 검증한다."""

from __future__ import annotations

import httpx
import pytest

from app.providers.seoul_citydata import (
    RealRealtimeCommercialProvider,
    map_realtime_commercial_response,
    map_realtime_parking_response,
    map_realtime_traffic_response,
)


def _payload() -> dict[str, object]:
    return {
        "citydata_cmrcl": {
            "RESULT": {"CODE": "INFO-000", "MESSAGE": "정상 처리되었습니다."},
            "row": [
                {
                    "AREA_NM": "용리단길",
                    "AREA_CD": "POI076",
                    "LIVE_CMRCL_STTS": [
                        {
                            "AREA_CMRCL_LVL": "보통 시간대",
                            "CMRCL_TIME": "2026-08-20 14:00",
                            "CMRCL_RSB": [
                                {
                                    "RSB_LRG_CTGR": "음식·음료",
                                    "RSB_MID_CTGR": "커피·음료",
                                    "RSB_PAYMENT_LVL": "바쁜 시간대",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    }


def _flat_payload() -> dict[str, object]:
    """2026-08-20 실 API에서 확인한 citydata_cmrcl 응답 형태."""

    return {
        "RESULT": {"resultCode": "INFO-000", "resultMsg": "정상 처리되었습니다."},
        "AREA_NM": "용리단길",
        "AREA_CD": "POI076",
        "LIVE_CMRCL_STTS": {
            "AREA_CMRCL_LVL": "보통 시간대",
            "CMRCL_TIME": "2026-08-20 14:00",
            "CMRCL_RSB": [
                {
                    "RSB_LRG_CTGR": "음식·음료",
                    "RSB_MID_CTGR": "커피·음료",
                    "RSB_PAYMENT_LVL": "바쁜 시간대",
                }
            ],
        },
    }


def test_map_realtime_commercial_response_extracts_cafe_category() -> None:
    result = map_realtime_commercial_response(_payload(), requested_area="POI076")

    assert result.area_name == "용리단길"
    assert result.area_code == "POI076"
    assert result.area_activity_level == "보통 시간대"
    assert result.observed_at == "2026-08-20 14:00"
    assert result.categories[0].middle_category == "커피·음료"
    assert result.categories[0].activity_level == "바쁜 시간대"


def test_map_realtime_commercial_response_supports_live_flat_payload() -> None:
    result = map_realtime_commercial_response(_flat_payload(), requested_area="용리단길")

    assert result.area_name == "용리단길"
    assert result.area_code == "POI076"
    assert result.categories[0].middle_category == "커피·음료"


@pytest.mark.asyncio
async def test_real_provider_uses_area_code_without_leaking_key() -> None:
    seen_path = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_path
        seen_path = request.url.path
        return httpx.Response(200, json=_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealRealtimeCommercialProvider(api_key="sensitive-key", client=client)
        wrapped = await provider.get_area_commercial_status("POI076")

    assert seen_path.endswith("/citydata_cmrcl/1/1/POI076")
    assert "sensitive-key" in seen_path  # 서울시 API는 인증키를 경로에 요구한다.
    assert wrapped.metadata.status.value == "success"
    assert wrapped.data.categories[0].large_category == "음식·음료"


def _citydata_payload(prk_stts: list[dict[str, object]]) -> dict[str, object]:
    return {"CITYDATA": {"AREA_NM": "교대역", "AREA_CD": "POI999", "PRK_STTS": prk_stts}}


def test_map_realtime_parking_response_labels_public_and_private_types() -> None:
    """PRK_TYPE 코드 → 공영/민영 매핑을 실측(교대역·강남역·홍대) 근거로 검증한다."""

    lots = map_realtime_parking_response(
        _citydata_payload(
            [
                {
                    "PRK_NM": "교대역 동측 공영주차장(구)",
                    "PRK_CD": "1",
                    "PRK_TYPE": "NW",
                    "ADDR": "서울특별시 서초구 서초대로 1",
                },
                {"PRK_NM": "경남 공영주차장(구)", "PRK_CD": "2", "PRK_TYPE": "NS"},
                {"PRK_NM": "하림인터네셔날 빌딩", "PRK_CD": "3", "PRK_TYPE": "BS"},
                {"PRK_NM": "서초세움주차장(민영)", "PRK_CD": "4", "PRK_TYPE": "NP"},
                {"PRK_NM": "코드 모르는 주차장", "PRK_CD": "5", "PRK_TYPE": "ZZ"},
            ]
        )
    )

    by_name = {lot.name: lot for lot in lots}
    assert by_name["교대역 동측 공영주차장(구)"].lot_type == "공영"
    assert by_name["교대역 동측 공영주차장(구)"].address == "서울특별시 서초구 서초대로 1"
    assert by_name["경남 공영주차장(구)"].lot_type == "공영"
    assert by_name["하림인터네셔날 빌딩"].lot_type == "민영"
    assert by_name["서초세움주차장(민영)"].lot_type == "민영"
    assert by_name["코드 모르는 주차장"].lot_type is None


def test_map_realtime_parking_response_dedupes_by_code_keeping_realtime_entry() -> None:
    """이촌한강공원 실측 — 같은 PRK_CD가 두 번 오면 실시간 정보가 있는 쪽을 남긴다."""

    lots = map_realtime_parking_response(
        _citydata_payload(
            [
                {
                    "PRK_NM": "이촌3, 4주차장",
                    "PRK_CD": "1892050",
                    "PRK_TYPE": "BP",
                    "CPCTY": "257",
                    "CUR_PRK_CNT": "",
                    "CUR_PRK_YN": "N",
                },
                {
                    "PRK_NM": "이촌3, 4주차장",
                    "PRK_CD": "1892050",
                    "PRK_TYPE": "BP",
                    "CPCTY": "257",
                    "CUR_PRK_CNT": "0",
                    "CUR_PRK_YN": "Y",
                    "CUR_PRK_TIME": "2025-02-03 09:06:31",
                },
            ]
        )
    )

    assert len(lots) == 1
    assert lots[0].current_available is True
    assert lots[0].current_parked_count == 0
    assert lots[0].available_spaces == 257
    assert lots[0].observed_at == "2025-02-03 09:06:31"


def test_map_realtime_traffic_response_extracts_avg_road_data() -> None:
    payload = {
        "CITYDATA": {
            "AREA_NM": "이촌한강공원",
            "ROAD_TRAFFIC_STTS": {
                "AVG_ROAD_DATA": {
                    "ROAD_MSG": "해당 장소로 이동·진입하는 도로가 크게 막히지 않아요.",
                    "ROAD_TRAFFIC_IDX": "원활",
                    "ROAD_TRAFFIC_SPD": 32,
                    "ROAD_TRAFFIC_TIME": "2026-08-26 19:15",
                },
                "ROAD_TRAFFIC_STTS": [],
            },
        }
    }

    result = map_realtime_traffic_response(payload)

    assert result is not None
    assert result.level == "원활"
    assert result.average_speed_kmh == 32.0
    assert result.message == "해당 장소로 이동·진입하는 도로가 크게 막히지 않아요."
    assert result.observed_at == "2026-08-26 19:15"


def test_map_realtime_traffic_response_returns_none_when_missing() -> None:
    assert map_realtime_traffic_response({"CITYDATA": {"AREA_NM": "종로"}}) is None
