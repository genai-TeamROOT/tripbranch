"""외부 API 거절 응답에서 원인 식별에 필요한 필드만 뽑는 공용 헬퍼.

역할: 4xx/5xx 응답 본문에서 upstream이 준 에러 코드·메시지를 추출한다.
입력: httpx.Response.
출력: 로그에 그대로 넣을 수 있는 한 줄 문자열.
호출 시점: provider가 HTTPStatusError를 잡아 로그를 남길 때 사용한다.

data.go.kr(기상청·KASI·TourAPI)은 인증 실패·활용기간 만료·트래픽 초과를 모두
같은 4xx로 내리고 구분은 본문 errMsg/returnReasonCode에만 담는다. Naver는
errorCode/errorMessage를 쓴다. 상태 코드만 봐서는 원인을 가릴 수 없어서 본문을
봐야 하지만, 통째로 남기면 불필요한 정보까지 로그에 들어가므로 알려진 키만 뽑는다.
"""

from __future__ import annotations

import re

import httpx

# JSON과 XML 응답 양쪽에서 같은 패턴으로 뽑는다 — data.go.kr은 dataType에 따라
# 둘 다 내려주고, 오류 응답은 요청한 형식을 무시하고 XML로 오는 경우도 있다.
_ERROR_KEYS = (
    "errMsg",
    "returnReasonCode",
    "returnAuthMsg",
    "resultCode",
    "resultMsg",
    "errorCode",
    "errorMessage",
    # Naver는 {"error":{"errorCode":.., "message":.., "details":..}} 형태로 준다.
    "message",
    "details",
)
_MAX_FALLBACK_CHARS = 200


def upstream_error_detail(response: httpx.Response) -> str:
    """거절 응답에서 알려진 에러 필드만 뽑아 한 줄로 만든다."""
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - 본문 접근 실패가 로깅 자체를 막으면 안 된다.
        return "body=<unavailable>"

    fields = {
        key: match.group(1).strip()
        for key in _ERROR_KEYS
        if (match := re.search(rf'[<"]{key}[>"]\s*:?\s*"?([^"<,}}]+)', text))
    }
    if fields:
        return ", ".join(f"{key}={value}" for key, value in fields.items())
    return f"body={' '.join(text.split())[:_MAX_FALLBACK_CHARS]}"
