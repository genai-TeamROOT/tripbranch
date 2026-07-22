"""실제 Provider 요청과 응답을 인증정보 없이 확인하는 수동 Inspection Test."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.providers.concentration import RealConcentrationProvider
from app.providers.geocoding import RealGeocodingProvider
from app.providers.real_place import RealPlaceProvider
from app.providers.weather import RealWeatherProvider

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.inspection,
    pytest.mark.skipif(
        os.getenv("RUN_REAL_PROVIDER_INSPECTION") != "true",
        reason="RUN_REAL_PROVIDER_INSPECTION=true일 때만 실제 요청·응답을 출력합니다.",
    ),
]

settings = Settings()
_REDACTED = "<redacted>"
_SENSITIVE_QUERY_KEYS = {"servicekey", "api_key", "apikey"}
_SENSITIVE_HEADER_KEYS = {
    "authorization",
    "x-ncp-apigw-api-key-id",
    "x-ncp-apigw-api-key",
}
_MAX_RESPONSE_CHARS = 30_000


def _required_value(name: str, value: str) -> str:
    if not value:
        pytest.skip(f"{name} 환경변수가 없습니다.")
    return value


def _sanitized_query(request: httpx.Request) -> dict[str, str | list[str]]:
    result: dict[str, str | list[str]] = {}
    for key, value in request.url.params.multi_items():
        safe_value = _REDACTED if key.lower() in _SENSITIVE_QUERY_KEYS else value
        existing = result.get(key)
        if existing is None:
            result[key] = safe_value
        elif isinstance(existing, list):
            existing.append(safe_value)
        else:
            result[key] = [existing, safe_value]
    return result


def _sanitized_headers(request: httpx.Request) -> dict[str, str]:
    visible_headers: dict[str, str] = {}
    for key, value in request.headers.items():
        normalized = key.lower()
        if normalized in _SENSITIVE_HEADER_KEYS:
            visible_headers[key] = _REDACTED
        elif normalized in {"accept", "content-type", "user-agent"}:
            visible_headers[key] = value
    return visible_headers


def _format_body(payload: Any) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(rendered) <= _MAX_RESPONSE_CHARS:
        return rendered
    omitted = len(rendered) - _MAX_RESPONSE_CHARS
    return f"{rendered[:_MAX_RESPONSE_CHARS]}\n... <{omitted} chars omitted>"


async def _print_request(request: httpx.Request) -> None:
    print("\n=== Provider Request ===")
    print(f"method: {request.method}")
    print(f"url: {request.url.copy_with(query=None)}")
    print(f"query: {_format_body(_sanitized_query(request))}")
    print(f"headers: {_format_body(_sanitized_headers(request))}")


async def _print_response(response: httpx.Response) -> None:
    await response.aread()
    print("=== Provider Response ===")
    print(f"status: {response.status_code}")
    print(f"content-type: {response.headers.get('content-type', '')}")
    try:
        payload: Any = response.json()
    except ValueError:
        payload = response.text
    print(_format_body(payload))


def _inspection_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        event_hooks={
            "request": [_print_request],
            "response": [_print_response],
        }
    )


async def test_inspect_naver_geocoding_request_and_response() -> None:
    async with _inspection_client() as client:
        provider = RealGeocodingProvider(
            api_key_id=_required_value("NAVER_MAP_CLIENT_ID", settings.naver_map_client_id),
            api_key=_required_value(
                "NAVER_MAP_CLIENT_SECRET", settings.naver_map_client_secret
            ),
            client=client,
        )
        result = await provider.geocode("경복궁")

    print(f"normalized: {result}")


async def test_inspect_kma_weather_request_and_response() -> None:
    async with _inspection_client() as client:
        provider = RealWeatherProvider(
            api_key=_required_value("WEATHER_API_KEY", settings.weather_api_key),
            client=client,
        )
        result = await provider.get_current_condition(37.5788, 126.9770)

    print(f"normalized: {result.value}")


async def test_inspect_tour_api_place_request_and_response() -> None:
    async with _inspection_client() as client:
        provider = RealPlaceProvider(
            api_key=_required_value("TOUR_API_SERVICE_KEY", settings.tour_api_service_key),
            client=client,
        )
        result = await provider.search_places(
            latitude=37.5788,
            longitude=126.9770,
            preferred_categories=[],
            search_radius_km=1.0,
        )

    print(f"normalized_count: {len(result)}")
    print(f"normalized_samples: {[candidate.name for candidate in result[:3]]}")


async def test_inspect_tour_api_concentration_request_and_response() -> None:
    async with _inspection_client() as client:
        provider = RealConcentrationProvider(
            api_key=_required_value("TOUR_API_SERVICE_KEY", settings.tour_api_service_key),
            client=client,
        )
        result = await provider.get_forecast("11", "11110", "경복궁")

    print(f"normalized_count: {len(result.forecasts)}")
    print(f"normalized_samples: {list(result.forecasts[:3])}")
