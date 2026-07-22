"""Provider 팩토리.

역할: 설정(Settings)의 provider 모드(fake/real)에 따라 알맞은 provider
      구현체를 선택해 반환한다. 서비스 계층은 이 팩토리만 알면 되고
      구체적인 provider 클래스를 직접 import하지 않는다.
입력: app.config.settings의 place_provider, geocoding_provider 값.
출력: PlaceProvider, GeocodingProvider protocol을 만족하는 인스턴스.
호출 시점: 서비스 계층이 provider가 필요할 때 호출한다.
TODO: RealPlaceProvider, RealGeocodingProvider 구현되면 분기에 연결한다.
"""

from __future__ import annotations

from app.config import settings
from app.providers.protocols import GeocodingProvider, PlaceProvider
from app.providers.stub import FakeGeocodingProvider, FakePlaceProvider


def get_geocoding_provider() -> GeocodingProvider:
    if settings.geocoding_provider == "real":
        raise NotImplementedError("RealGeocodingProvider가 아직 구현되지 않았습니다.")
    return FakeGeocodingProvider()


def get_place_provider() -> PlaceProvider:
    if settings.place_provider == "real":
        from app.providers.real_place import RealPlaceProvider

        return RealPlaceProvider()
    return FakePlaceProvider()