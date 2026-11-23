"""Supabase 무료 플랜의 유휴 정지를 막기 위해 DB에 쓰기를 한 번 남긴다.

역할: keepalive_pings 표의 행 하나(id = 'default')의 pinged_at을 지금으로 갱신한다.
갱신(쓰기)이 목적이고 이 값을 읽는 쪽은 없다.
입력: --source(어느 경로가 찔렀는지, 기본 manual). 접속 정보는 SUPABASE_URL과
SUPABASE_SECRET_KEY 환경변수에서 읽는다.
출력: 갱신한 시각. 실패하면 비0으로 종료한다.
호출 시점: .github/workflows/keepalive.yml이 하루 세 번 호출한다. 수동 실행은
`python -m scripts.ping_database`.

**조회로는 정지를 막지 못한다.** 2026-11-23에 정지 예정 경고가 왔을 때
cleanup_expired_sessions.py는 매일 성공하고 있었다. 다만 11-17부터 지울 세션이
없어 select만 나갔다. 10월에는 매일 지울 세션이 있어 삭제가 함께 일어나 경고가
오지 않았다. 그래서 이 스크립트는 반드시 쓰기를 한다.

하루 한 번이 아니라 세 번 도는 이유는, 공식 문서가 "하루 몇 건의 요청"이라고만
말해 한 건으로 충분한지 확인할 수 없기 때문이다. 한 번이 실패해도 그날 몫이 남는다.

세션 저장소(app.state.supabase_store)를 쓰지 않고 REST를 직접 부른다 -- 이 표는
에이전트 상태와 무관하고, 그쪽 계약에 keepalive용 메서드를 넣을 이유가 없다.

키는 로그에도 예외 메시지에도 남기지 않는다. 실패를 알릴 때 상태 코드와 응답
본문만 쓴다(providers/weather.py가 예외 처리에서 request_params.clear()를 하는
것과 같은 이유).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import httpx

from app.config import settings
from app.state.schema import now_kst

_TABLE = "keepalive_pings"
_ROW_ID = "default"
_TIMEOUT = 15.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supabase에 keepalive 쓰기를 남긴다")
    parser.add_argument(
        "--source",
        default="manual",
        help="어느 경로가 찔렀는지 기록한다 (기본 manual)",
    )
    return parser


def ping(source: str) -> str:
    """pinged_at을 지금으로 갱신하고 그 시각을 반환한다."""
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise SystemExit(
            "SUPABASE_URL·SUPABASE_SECRET_KEY가 비어 있습니다 —"
            " 쓰기를 보낼 대상이 없습니다."
        )

    pinged_at = now_kst().isoformat()
    # 행이 이미 있으면 갱신한다(merge-duplicates). 표의 default now()는 insert
    # 때만 적용되므로 시각을 명시해 보낸다.
    try:
        response = httpx.post(
            f"{settings.supabase_url.rstrip('/')}/rest/v1/{_TABLE}",
            params={"on_conflict": "id"},
            headers={
                "apikey": settings.supabase_secret_key,
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=[{"id": _ROW_ID, "pinged_at": pinged_at, "source": source}],
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        # 예외 본문에 키가 들어가지 않도록 종류만 옮긴다.
        raise SystemExit(f"Supabase에 연결하지 못했습니다: {type(exc).__name__}") from None

    if response.status_code >= 400:
        raise SystemExit(
            f"쓰기가 거부됐습니다 (HTTP {response.status_code}): {response.text[:300]}"
        )

    return pinged_at


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"keepalive 갱신: {ping(args.source)} (source={args.source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
