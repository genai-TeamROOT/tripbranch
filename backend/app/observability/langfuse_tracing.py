"""Langfuse(LLMOps 관측)로 나가는 전송을 한 곳에서 감싼다.

역할: SDK 클라이언트의 생성·수명·마스킹을 여기서만 다룬다. 호출부는 이 모듈의
헬퍼만 쓰고 `langfuse` 패키지를 직접 import 하지 않는다 — 켜고 끄는 규칙과
마스킹이 한 군데를 못 벗어나게 하려는 것이다.
입력: `app.config.settings`의 `langfuse_*` 값.
출력: 켜져 있으면 Langfuse로 span/generation 전송, 꺼져 있으면 아무 동작 없음.
호출 시점: 부팅(검증), 요청 처리 중(계측), 종료(flush).

관측 전용이다 — 여기 값이 없거나 틀려도 추천 판정은 달라지지 않는다.
`api_usage`가 "몇 번 불렀나", `api_exchanges`가 "무엇을 주고받았나"라면 이쪽은
"한 턴이 어느 단계를 어떤 버전으로 얼마나 걸려 지나갔나"다.

**스위치가 두 개인 이유.** `langfuse_enabled`는 "전송을 하느냐",
`langfuse_capture_content`는 "발화·응답 원문을 실어 보내느냐"다. 하나로 묶으면
배포 환경에서 지연·토큰만 보고 원문은 빼는 선택을 할 수 없다. 둘 다 기본 off라
켜는 쪽이 명시적 선택이다(`taste_evidence_enabled`와 같은 이유).

보안 — **모르면 막는 쪽으로 둔다.** `capture_content`가 꺼져 있으면 mask 훅이
**input·output·metadata를 전부** 치환한다. "입력만 가리고 메타데이터는 남긴다"가
불가능하기 때문이다: SDK가 mask 함수에 `data`만 넘기고 어느 필드인지는 안 알려준다
(`_client/span.py::_mask_attribute`). 그래서 **가려지면 안 되는 값(프롬프트·Scoring
버전)은 `metadata`가 아니라 `trace_attributes()`의 `version`·`tags`로 싣는다** —
그 둘은 mask를 타지 않는다. `api_exchanges.py`가 "분류되지 않은 host는 값 전부를
마스킹한다"로 택한 것과 같은 원칙이다.

**Tool 인자·응답을 계측하는 헬퍼는 의도적으로 두지 않는다.** 사용자 좌표(장소
검색·경로 조회)와 외부 API 자격증명이 그 경로로만 흐른다. 헬퍼가 없으면 실수로도
못 쓴다. Tool 단계가 남기는 것은 **집계뿐이다** — 몇 건 요청해 몇 건이 성공했나,
Provider별 상태가 무엇인가. 그 요약은 호출부가 직접 고르며(`_summarize_tool_fetch`,
`tools/travel_route.py::summarize_fanout`), 인자와 응답 원문은 거기서 걸러낸다.

**마스킹을 타는 자리와 안 타는 자리를 나눠 쓴다.** `input`·`output`·`metadata`만
mask를 거치고(`_client/span.py::_process_media_and_apply_mask`), `level`·
`status_message`·`version`은 그대로 나간다. 그래서 `capture_content`가 꺼져도 남아야
하는 운영 신호(예: 경로 실측/추정 비율)는 `status_message`에도 한 줄로 싣는다.

실패는 전부 흡수한다 — 관측이 사용자 응답을 막으면 안 된다
(`runtime/agent_runtime.py::_record_trace_safely()`가 쓰는 것과 같은 원칙). 다만
**흡수하는 건 관측 자신의 실패지 호출부의 실패가 아니다**(`_guard()` 참고).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from app.config import Settings, settings

logger = logging.getLogger(__name__)

# 마스킹된 자리에 남길 값. Langfuse 화면에서 "값이 없다"와 "일부러 가렸다"가
# 구분돼야 설정을 의심할 수 있다.
REDACTED = "<redacted by tripbranch>"

# 켜져 있을 때만 만든다. 생성 자체가 OpenTelemetry provider를 세팅하므로
# 꺼져 있을 때는 그 비용도 부작용도 없어야 한다.
_client: Any | None = None
# 초기화가 한 번 실패하면 매 요청마다 다시 시도하지 않는다.
_client_failed = False


def is_enabled() -> bool:
    """전송이 켜져 있는가."""
    return settings.langfuse_enabled


def captures_content() -> bool:
    """발화·응답 원문을 실어 보내는가. 전송이 꺼져 있으면 당연히 아니다."""
    return settings.langfuse_enabled and settings.langfuse_capture_content


def _mask(*, data: Any, **_: Any) -> Any:
    """`capture_content`가 꺼져 있으면 실려 나갈 값을 전부 치환한다.

    호출 시점에 설정을 다시 읽는다 — 클라이언트를 다시 만들지 않고도 켜고 끌 수
    있어야 하고, 테스트가 설정만 바꿔 검증할 수 있어야 한다.
    """
    return data if captures_content() else REDACTED


def validate_langfuse_config(target: Settings | None = None) -> None:
    """켜져 있는데 자격증명이 비어 있으면 부팅에서 막는다.

    실패는 첫 요청이 아니라 부팅에서 드러나야 한다(D-042). 관측은 조용히 안 되면
    "켠 줄 알았는데 아무것도 안 쌓이는" 상태가 며칠씩 간다.
    누락 항목을 하나씩 발견해 재시작하는 왕복을 없애려고 전부 모아서 보고한다
    (`providers/factory.py::validate_provider_config()`와 같은 방식).
    """
    current = target if target is not None else settings
    if not current.langfuse_enabled:
        return
    missing = [
        variable_name
        for variable_name, value in (
            ("LANGFUSE_PUBLIC_KEY", current.langfuse_public_key),
            ("LANGFUSE_SECRET_KEY", current.langfuse_secret_key),
            ("LANGFUSE_BASE_URL", current.langfuse_base_url),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "LANGFUSE_ENABLED=true인데 필요한 환경변수가 비어 있습니다: " + ", ".join(missing)
        )


def get_tracer() -> Any | None:
    """켜져 있으면 Langfuse 클라이언트를, 아니면 `None`을 돌려준다.

    꺼져 있을 때는 `langfuse`를 import조차 하지 않는다.
    """
    global _client, _client_failed
    if not is_enabled():
        return None
    if _client is not None or _client_failed:
        return _client
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            # 로컬과 배포 기록이 한 프로젝트에 섞이면 비교가 무의미해진다.
            environment=settings.app_env,
            mask=_mask,
        )
    except Exception:
        _client_failed = True
        logger.warning("Langfuse 초기화 실패 — 관측만 꺼진다", exc_info=True)
    return _client


def shutdown() -> None:
    """대기 중인 전송을 내보내고 백그라운드 스레드를 정리한다.

    캐시도 함께 비우므로 테스트가 설정을 바꿔가며 재초기화하는 데도 쓴다.
    """
    global _client, _client_failed
    client, _client, _client_failed = _client, None, False
    if client is None:
        return
    try:
        client.shutdown()
    except Exception:
        logger.warning("Langfuse 종료 실패(응답 흐름에는 영향 없음)", exc_info=True)


def _close(manager: Any, exc: BaseException | None) -> None:
    try:
        if exc is None:
            manager.__exit__(None, None, None)
        else:
            manager.__exit__(type(exc), exc, exc.__traceback__)
    except Exception:
        logger.warning("Langfuse 관측 종료 실패(응답 흐름에는 영향 없음)", exc_info=True)


@contextmanager
def _guard(factory: Callable[[], Any]) -> Iterator[Any]:
    """관측용 context manager를 감싸 **진입·종료 실패만** 흡수한다.

    본문에서 난 예외는 그대로 올린다 — 관측이 삼켜도 되는 건 자기 실패지 호출부의
    실패가 아니다. 그래서 `with` 전체를 try로 감싸지 않는다(그러면 호출부 예외까지
    먹는다). 진입에 실패하면 `None`을 넘겨, 호출부는 계측 없이 그대로 진행한다.
    """
    try:
        manager = factory()
        entered = manager.__enter__()
    except Exception:
        logger.warning("Langfuse 관측 시작 실패(응답 흐름에는 영향 없음)", exc_info=True)
        yield None
        return
    try:
        yield entered
    except BaseException as exc:
        _close(manager, exc)
        raise
    _close(manager, None)


class _Recorder:
    """관측 객체에 값을 붙이되 실패를 호출부로 올리지 않는다."""

    __slots__ = ("_span",)

    def __init__(self, span: Any) -> None:
        self._span = span

    def record(self, **fields: Any) -> None:
        """`output`·`usage_details`·`level` 등 SDK가 받는 필드를 그대로 넘긴다.

        `None`은 걸러낸다 — 값이 없는 것과 "None으로 덮어쓴 것"은 다르다.
        """
        payload = {key: value for key, value in fields.items() if value is not None}
        if not payload:
            return
        try:
            self._span.update(**payload)
        except Exception:
            logger.warning("Langfuse 관측 기록 실패(응답 흐름에는 영향 없음)", exc_info=True)


class _NoopRecorder:
    """꺼져 있거나 관측 시작에 실패했을 때 호출부가 분기하지 않게 하는 자리."""

    __slots__ = ()

    def record(self, **fields: Any) -> None:
        return


_NOOP: _NoopRecorder = _NoopRecorder()


@contextmanager
def trace_attributes(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    version: str | None = None,
    tags: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[None]:
    """이 블록 안에서 생기는 모든 관측에 trace 단위 속성을 붙인다.

    `version`·`tags`는 mask를 타지 않는다 — 프롬프트·Scoring 버전처럼 `capture_content`
    가 꺼져 있어도 남아야 하는 값은 `metadata`가 아니라 여기에 싣는다(모듈 docstring).
    """
    if get_tracer() is None:
        yield
        return

    def factory() -> Any:
        from langfuse import propagate_attributes

        return propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            version=version,
            tags=list(tags) or None,
            metadata=dict(metadata) if metadata else None,
        )

    with _guard(factory):
        yield


@contextmanager
def observe_step(
    name: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[_Recorder | _NoopRecorder]:
    """실행 단계 하나를 span으로 남긴다. 지연은 SDK가 잰다.

    `name`은 B의 Trace `step`과 같은 값을 쓴다(`llm_interpret`·`scoring` 등) —
    두 기록을 나란히 읽으려면 이름이 갈리면 안 된다.
    """
    client = get_tracer()
    if client is None:
        yield _NOOP
        return

    def factory() -> Any:
        return client.start_as_current_observation(
            as_type="span",
            name=name,
            metadata=dict(metadata) if metadata else None,
        )

    with _guard(factory) as span:
        yield _NOOP if span is None else _Recorder(span)


@contextmanager
def observe_generation(
    name: str,
    *,
    model: str | None = None,
    version: str | None = None,
    input: Any = None,
) -> Iterator[_Recorder | _NoopRecorder]:
    """LLM 호출 하나를 generation으로 남긴다.

    토큰은 호출부가 응답을 받은 뒤 넘긴다:
    `recorder.record(output=..., usage_details={"input_tokens": n, "output_tokens": m})`

    `input`·`output`은 `capture_content`가 꺼져 있으면 mask가 치환한다. 호출부는
    가리는 걸 신경 쓰지 않고 있는 그대로 넘긴다 — 판단을 한 곳에 모아 둔다.

    `version`은 **mask를 타지 않는다.** 프롬프트 버전이 여기 들어가는 이유가 그것이다 —
    원문 수집을 꺼도 "어느 버전이 이 지연·토큰을 냈나"는 남아야 배포 환경에서도
    버전 비교가 된다(모듈 docstring).
    """
    client = get_tracer()
    if client is None:
        yield _NOOP
        return

    def factory() -> Any:
        return client.start_as_current_observation(
            as_type="generation", name=name, model=model, version=version, input=input
        )

    with _guard(factory) as generation:
        yield _NOOP if generation is None else _Recorder(generation)


# LangGraph 노드는 `observe_step()`으로 직접 감싼다(graph/__init__.py). Langfuse가
# 주는 LangChain CallbackHandler를 쓰지 않는 이유는 그게 **`langchain` 본체를
# 요구하기 때문**이다 — 우리는 langgraph가 끌고 온 `langchain-core`만 두고
# 본체·통합 패키지는 의도적으로 안 넣었다(pyproject.toml). 콜백 하나 때문에 그
# 무거운 의존성을 들이는 것보다, 노드를 직접 감싸 이름까지 우리가 정하는 편이 낫다
# (B의 Trace `step`과 같은 이름을 쓸 수 있다).
__all__ = [
    "REDACTED",
    "captures_content",
    "is_enabled",
    "observe_generation",
    "observe_step",
    "shutdown",
    "trace_attributes",
    "validate_langfuse_config",
]
