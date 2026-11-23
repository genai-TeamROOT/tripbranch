"""keepalive 쓰기 스크립트 테스트.

**이 스크립트는 조회가 아니라 쓰기를 해야 의미가 있다.** 2026-11-23 정지 예정
경고가 온 원인이 바로 그것이다 — 세션 정리는 매일 성공했지만 지울 세션이 없는
날에는 select만 나갔고, 조회는 활동으로 집계되지 않았다. 그래서 여기서는 요청이
POST로 나가고 갱신 본문이 실려 있는지를 못 박는다. 호출됐다는 사실만 확인하면
나중에 조회로 바뀌어도 테스트가 통과해 같은 사고가 반복된다.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import settings
from scripts.ping_database import main, ping


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


@pytest.fixture
def supabase_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "test-secret-key")


def test_쓰기_요청으로_나가고_갱신_본문이_실린다(
    monkeypatch: pytest.MonkeyPatch, supabase_settings: None
) -> None:
    calls: list[dict[str, object]] = []

    def fake_post(url: str, **kwargs: object) -> _Response:
        calls.append({"url": url, **kwargs})
        return _Response(204)

    monkeypatch.setattr(httpx, "post", fake_post)

    pinged_at = ping("test-source")

    assert len(calls) == 1
    call = calls[0]
    assert call["url"].endswith("/rest/v1/keepalive_pings")

    # 갱신이어야 한다 — 행이 이미 있어도 덮어써야 쓰기가 매번 생긴다.
    prefer = call["headers"]["Prefer"]
    assert "resolution=merge-duplicates" in prefer
    assert call["params"] == {"on_conflict": "id"}

    body = call["json"]
    assert body == [
        {"id": "default", "pinged_at": pinged_at, "source": "test-source"}
    ]


def test_설정이_비면_쓰기를_시도하지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_secret_key", "")

    def fail_post(*args: object, **kwargs: object) -> _Response:
        raise AssertionError("설정이 비었는데 요청을 보냈다")

    monkeypatch.setattr(httpx, "post", fail_post)

    with pytest.raises(SystemExit) as caught:
        ping("test-source")

    assert "SUPABASE_URL" in str(caught.value)


def test_거부되면_실패로_끝난다(
    monkeypatch: pytest.MonkeyPatch, supabase_settings: None
) -> None:
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _Response(401, "Invalid API key")
    )

    with pytest.raises(SystemExit) as caught:
        ping("test-source")

    assert "401" in str(caught.value)


def test_연결_실패_메시지에_키가_남지_않는다(
    monkeypatch: pytest.MonkeyPatch, supabase_settings: None
) -> None:
    def raise_connect_error(*args: object, **kwargs: object) -> _Response:
        raise httpx.ConnectError("connect failed")

    monkeypatch.setattr(httpx, "post", raise_connect_error)

    with pytest.raises(SystemExit) as caught:
        ping("test-source")

    message = str(caught.value)
    assert "ConnectError" in message
    assert "test-secret-key" not in message


def test_main은_성공하면_0을_돌려준다(
    monkeypatch: pytest.MonkeyPatch, supabase_settings: None
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Response(204))

    assert main(["--source", "github-actions"]) == 0
