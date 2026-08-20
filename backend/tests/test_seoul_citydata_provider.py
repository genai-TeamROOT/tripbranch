"""서울시 실시간 상권현황 Provider의 응답 정규화를 검증한다."""

from __future__ import annotations

import httpx
import pytest

from app.providers.seoul_citydata import (
    RealRealtimeCommercialProvider,
    map_realtime_commercial_response,
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
