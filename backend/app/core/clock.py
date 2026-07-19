# 추천 로직이 "지금이 몇 시인지"를 알아야 할 때 항상 거쳐야 하는 시간 공급자 추상화.
# API route나 서비스 코드에서 datetime.now()를 직접 호출하지 않는다 - 그 대신 이 모듈의
# Clock을 주입받아 clock.now()를 쓴다. 이렇게 하면:
#   - 운영 환경: SystemClock -> 실제 현재 시각
#   - Fake Provider 환경(개발/테스트/데모): FixedClock -> 항상 재현 가능한 고정 시각
# 을 설정 하나(core/config.py의 FAKE_CURRENT_DATETIME, api/deps.py의 get_clock)로 스위칭할 수 있다.
# 대한민국 MVP 기준이며 naive datetime을 그대로 사용한다(기존 domain/operating_hours.py와
# 동일한 방식 - 시간대 처리 라이브러리를 새로 들이지 않는다).

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """실제 운영 환경에서 사용. 매 호출마다 실제 현재 시각을 반환한다."""

    def now(self) -> datetime:
        return datetime.now()


class FixedClock:
    """개발/테스트/데모에서 사용. 생성 시 고정된 시각을 항상 반환한다 -
    실행 시각과 무관하게 결과가 재현 가능해야 하는 곳(Fake 추천 흐름, pytest)에 쓴다."""

    def __init__(self, fixed_datetime: datetime) -> None:
        self._fixed_datetime = fixed_datetime

    def now(self) -> datetime:
        return self._fixed_datetime
