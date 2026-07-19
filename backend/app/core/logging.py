# 표준 logging 모듈 초기화. APP_ENV가 local이면 DEBUG, 아니면 INFO 레벨로 설정한다.
# 사용법: app/main.py의 create_app()에서 앱 시작 시 한 번 호출됨. 각 모듈에서는
# `logging.getLogger(__name__)`으로 로거를 얻어 쓰면 됨(별도 설정 불필요).
# TODO: 운영 환경에서 구조화 로깅(JSON)이나 외부 로그 수집기 연동이 필요해지면 여기서 확장할 것.

from __future__ import annotations

import logging


def configure_logging(app_env: str) -> None:
    level = logging.DEBUG if app_env == "local" else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
