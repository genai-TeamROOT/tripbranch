"""프롬프트 원문을 Langfuse에서 읽어 온다. 실패하면 레포의 Markdown으로 돌아간다.

역할: `app/prompts/loader.py`가 디스크를 읽기 전에 여기에 먼저 물어본다. `langfuse`
패키지를 직접 만지는 곳은 `langfuse_tracing`과 여기 둘뿐이다.
입력: `settings.langfuse_prompts_enabled`, 자산의 상대경로(`recommend/extract.md`).
출력: 프롬프트 원문 문자열. 자리표시자(`{{name}}`)는 **치환하지 않고 그대로** 준다.
호출 시점: 프롬프트를 조립할 때마다(대부분 캐시 적중, 실측 0.006ms).

**`compile()`을 쓰지 않는다.** Langfuse도 `{{name}}` 문법이라 쓸 수 있지만, 그러면
치환 엔진이 둘이 된다 — 폴백으로 디스크를 읽는 순간 `loader.render_text()`가 돌고,
정상 경로는 SDK가 돈다. 두 결과가 어긋나도 아무도 모른다. 그래서 여기서는 **원문만**
가져오고 치환은 항상 `loader`가 한다. (스파이크에서 두 결과가 바이트 단위로 같음을
확인했지만, 같다는 것과 앞으로도 같다는 것은 다르다.)

**이름 대응은 확장자만 뗀다.** `recommend/extract.md` → `recommend/extract`. Langfuse가
`/`를 폴더로 다루므로 레포 구조가 화면에 그대로 보인다. 다만 **API 경로에 넣을 때는
URL 인코딩이 필요하다** — SDK의 `api.prompts.delete()`가 그걸 안 해서 폴더형 이름에
404가 난다(2026-08-25 실측). 조회는 SDK가 알아서 처리한다.

실패는 전부 흡수한다. Langfuse가 죽어도, 키가 없어도, 그 이름의 프롬프트가 아직
없어도 디스크 원문으로 돌아간다 — 프롬프트를 못 읽으면 답변 자체가 안 나가므로
여기서 예외를 올리면 관측 설정 하나로 서비스가 멈춘다.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from app.config import settings
from app.observability.langfuse_tracing import get_prompt_client

logger = logging.getLogger(__name__)

_MARKDOWN_SUFFIX: Final = ".md"

# 폴백으로 돌아간 이름. 한 번씩만 알리고 이후에는 조용히 넘어간다 — 프롬프트는
# 요청마다 여러 번 읽히므로 매번 찍으면 로그가 그것만 남는다.
_warned: set[str] = set()


def prompt_name(relative_path: str) -> str:
    """자산 경로를 Langfuse 프롬프트 이름으로 바꾼다.

    `push`·`check`·조회가 **같은 함수를 쓴다.** 각자 문자열을 만들면 한쪽만 바뀌었을 때
    조용히 다른 프롬프트를 보게 된다.
    """

    return relative_path.removesuffix(_MARKDOWN_SUFFIX)


def is_enabled() -> bool:
    """프롬프트를 Langfuse에서 읽는가."""

    return settings.langfuse_prompts_enabled


def fetch_text(relative_path: str, *, fallback: str) -> str:
    """프롬프트 원문. 못 가져오면 `fallback`(디스크 원문)을 그대로 돌려준다.

    SDK가 캐시를 들고 있어 대부분은 왕복이 없다. 만료되면 **백그라운드로 갱신하고
    기존 값을 즉시** 돌려주므로 요청이 막히지 않는다(`_client/client.py::get_prompt`).
    """

    client = get_prompt_client()
    if client is None:
        return fallback

    name = prompt_name(relative_path)
    try:
        prompt: Any = client.get_prompt(
            name,
            fallback=fallback,
            cache_ttl_seconds=settings.langfuse_prompt_cache_ttl_seconds,
        )
    except Exception:
        _warn_once(name, "조회 실패")
        return fallback

    # SDK는 fetch에 실패하면 fallback으로 만든 객체를 돌려주고 표시를 남긴다.
    # 표시가 있으면 **켰는데 디스크로 돌고 있다**는 뜻이라 알려야 한다 — 조용하면
    # "Langfuse에서 고쳤는데 왜 그대로지"로 며칠 간다.
    if getattr(prompt, "is_fallback", False):
        _warn_once(name, "Langfuse에 없거나 조회 실패")
        return fallback

    text = getattr(prompt, "prompt", None)
    if not isinstance(text, str):
        _warn_once(name, f"text 프롬프트가 아니다({type(text).__name__})")
        return fallback
    return text


def _warn_once(name: str, reason: str) -> None:
    if name in _warned:
        return
    _warned.add(name)
    logger.warning(
        "프롬프트를 디스크에서 읽는다 — %s: %s (레포 원문으로 계속 동작한다)", name, reason
    )


def reset_fallback_warnings() -> None:
    """폴백 경고 기록을 지운다. 테스트와 동기화 스크립트가 쓴다."""

    _warned.clear()


__all__ = [
    "fetch_text",
    "is_enabled",
    "prompt_name",
    "reset_fallback_warnings",
]
