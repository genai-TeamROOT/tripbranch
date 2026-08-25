"""Langfuse 관측 층이 **켜기 전까지 아무 일도 안 하고, 켜도 응답을 못 막는지** 검증한다.

이 스위트가 지키는 성질 세 가지.

1. **기본값이 꺼짐이다.** 지금은 실사용자가 없어(로컬 개발만) 나가는 게 팀원 자기
   발화뿐이지만, 그 조건에서 정한 기본값이 배포 이후까지 살아남으면 남의 발화가
   외부로 나간다. 문서에 "나중에 다시 보자"고 적는 건 안 지켜지므로 여기서 잠근다
   (package_D/[계획] Langfuse 도입 §6.3).
2. **관측 실패가 사용자 응답을 막지 않는다.** 반대로 **호출부의 예외는 삼키지
   않는다** — 관측이 먹어도 되는 건 자기 실패뿐이다.
3. **원문 마스킹이 한 곳에서 걸린다.** 2단계에서 붙일 LangChain CallbackHandler는
   노드 입출력을 자동 수집하므로, 호출부마다 가리는 방식으로는 새 나간다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings, settings
from app.observability import langfuse_tracing
from app.observability.langfuse_tracing import (
    REDACTED,
    callback_handler,
    captures_content,
    is_enabled,
    observe_generation,
    observe_step,
    trace_attributes,
    validate_langfuse_config,
)


@pytest.fixture(autouse=True)
def _clear_client_cache() -> Any:
    """클라이언트 캐시는 프로세스 단위라 테스트 간에 새지 않도록 매번 비운다."""
    langfuse_tracing.shutdown()
    yield
    langfuse_tracing.shutdown()


def _enable(monkeypatch: pytest.MonkeyPatch, *, capture_content: bool = False) -> None:
    monkeypatch.setattr(settings, "langfuse_enabled", True)
    monkeypatch.setattr(settings, "langfuse_capture_content", capture_content)


class _FakeSpan:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update(self, **fields: Any) -> None:
        self.updates.append(fields)


class _FakeObservation:
    """`start_as_current_observation()`이 돌려주는 context manager 흉내."""

    def __init__(self, span: _FakeSpan, *, fail_on_exit: bool = False) -> None:
        self._span = span
        self._fail_on_exit = fail_on_exit
        self.exited_with: type[BaseException] | None = None

    def __enter__(self) -> _FakeSpan:
        return self._span

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.exited_with = exc_type
        if self._fail_on_exit:
            raise RuntimeError("전송 실패")
        return False


class _FakeClient:
    def __init__(self, span: _FakeSpan | None = None, **kwargs: Any) -> None:
        self.span = span or _FakeSpan()
        self.kwargs = kwargs
        self.observations: list[_FakeObservation] = []

    def start_as_current_observation(self, **_: Any) -> _FakeObservation:
        observation = _FakeObservation(self.span, **self.kwargs)
        self.observations.append(observation)
        return observation


def _install(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(langfuse_tracing, "_client", client)
    monkeypatch.setattr(langfuse_tracing, "_client_failed", False)


# --- 1. 기본값이 꺼짐이다 (설계 잠금) ------------------------------------------


def test_both_switches_default_to_off() -> None:
    """`.env` 없이 만든 Settings에서 둘 다 꺼져 있어야 한다.

    **이 테스트가 실패하면 기본값을 바꾼 것이다.** 배포 환경에서 남의 발화가
    외부로 나가기 시작하므로, 통과시키기 전에 §6.3을 다시 읽어야 한다.
    """
    fresh = Settings(_env_file=None)

    assert fresh.langfuse_enabled is False
    assert fresh.langfuse_capture_content is False


def test_content_capture_stays_off_even_if_only_it_is_turned_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전송이 꺼져 있으면 원문 수집도 꺼진 것으로 본다 — 두 값이 어긋나지 않게."""
    monkeypatch.setattr(settings, "langfuse_enabled", False)
    monkeypatch.setattr(settings, "langfuse_capture_content", True)

    assert is_enabled() is False
    assert captures_content() is False


def test_public_surface_has_no_tool_argument_helper() -> None:
    """Tool 인자·응답을 계측하는 헬퍼는 **의도적으로 없다.**

    사용자 좌표(장소 검색·경로 조회)와 외부 API 자격증명이 그 경로로만 흐른다.
    헬퍼가 없으면 실수로도 못 쓴다. 이 목록을 늘리려면 §6.3을 먼저 읽어야 한다.
    """
    assert set(langfuse_tracing.__all__) == {
        "REDACTED",
        "callback_handler",
        "captures_content",
        "is_enabled",
        "observe_generation",
        "observe_step",
        "shutdown",
        "trace_attributes",
        "validate_langfuse_config",
    }


# --- 2. 꺼져 있으면 아무 일도 안 한다 -------------------------------------------


def test_disabled_never_creates_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """클라이언트 생성이 OpenTelemetry provider를 세팅하므로 꺼져 있으면 만들지 않는다."""
    monkeypatch.setattr(settings, "langfuse_enabled", False)

    with observe_step("scoring"), observe_generation("llm_interpret"), trace_attributes():
        pass

    assert langfuse_tracing._client is None


def test_disabled_helpers_hand_back_a_no_op_recorder(monkeypatch: pytest.MonkeyPatch) -> None:
    """호출부가 켜짐/꺼짐으로 분기하지 않아도 되게 항상 같은 모양을 준다."""
    monkeypatch.setattr(settings, "langfuse_enabled", False)

    with observe_step("scoring") as step:
        step.record(output="무시된다", usage_details={"input_tokens": 1})
    with observe_generation("llm_interpret", model="gemini") as generation:
        generation.record(output="무시된다")

    assert callback_handler() is None


# --- 3. 마스킹 -----------------------------------------------------------------


def test_mask_redacts_everything_when_content_capture_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`capture_content`가 꺼져 있으면 mask에 들어온 값을 전부 치환한다.

    SDK가 mask 함수에 어느 필드인지 안 알려주므로(`_mask_attribute`) "입력만 가리고
    메타데이터는 남긴다"가 불가능하다. 모르면 막는 쪽으로 둔다.
    """
    _enable(monkeypatch, capture_content=False)

    assert langfuse_tracing._mask(data="경복궁 근처 조용한 카페") == REDACTED
    assert langfuse_tracing._mask(data={"gps": [37.5796, 126.977]}) == REDACTED
    assert langfuse_tracing._mask(data=None) == REDACTED


def test_mask_passes_data_through_when_content_capture_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, capture_content=True)

    assert langfuse_tracing._mask(data="경복궁 근처 조용한 카페") == "경복궁 근처 조용한 카페"


def test_mask_rereads_the_setting_on_every_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """클라이언트를 다시 만들지 않고도 원문 수집만 끌 수 있어야 한다."""
    _enable(monkeypatch, capture_content=True)
    assert langfuse_tracing._mask(data="원문") == "원문"

    monkeypatch.setattr(settings, "langfuse_capture_content", False)
    assert langfuse_tracing._mask(data="원문") == REDACTED


# --- 4. 부팅 검증 ---------------------------------------------------------------


def test_boot_fails_when_enabled_without_credentials() -> None:
    """실패는 첫 요청이 아니라 부팅에서 드러나야 한다(D-042).

    조용히 안 되면 "켠 줄 알았는데 아무것도 안 쌓이는" 상태가 며칠씩 간다.
    """
    target = Settings(_env_file=None, langfuse_enabled=True)

    with pytest.raises(ValueError) as error:
        validate_langfuse_config(target)

    # 누락 항목을 하나씩 발견해 재시작하는 왕복이 없게 전부 모아서 보고한다.
    assert "LANGFUSE_PUBLIC_KEY" in str(error.value)
    assert "LANGFUSE_SECRET_KEY" in str(error.value)


def test_boot_passes_when_disabled_even_without_credentials() -> None:
    validate_langfuse_config(Settings(_env_file=None))


def test_boot_passes_when_enabled_with_credentials() -> None:
    validate_langfuse_config(
        Settings(
            _env_file=None,
            langfuse_enabled=True,
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
    )


# --- 5. 관측 실패가 응답을 막지 않는다 ------------------------------------------


def test_client_initialization_failure_only_turns_observability_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(langfuse_tracing, "_client", None)
    monkeypatch.setattr(langfuse_tracing, "_client_failed", False)

    def _explode(**_: Any) -> Any:
        raise RuntimeError("초기화 실패")

    monkeypatch.setitem(
        __import__("sys").modules, "langfuse", type("_M", (), {"Langfuse": _explode})
    )

    with observe_step("scoring") as step:
        step.record(output="무시된다")

    assert langfuse_tracing._client_failed is True


def test_observation_start_failure_does_not_break_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)

    class _Broken:
        def start_as_current_observation(self, **_: Any) -> Any:
            raise RuntimeError("시작 실패")

    _install(monkeypatch, _Broken())

    reached = False
    with observe_step("scoring") as step:
        step.record(output="무시된다")
        reached = True

    assert reached is True


def test_observation_exit_failure_does_not_break_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전송은 종료 시점에 일어난다 — 여기서 터지는 게 가장 위험하다."""
    _enable(monkeypatch)
    _install(monkeypatch, _FakeClient(fail_on_exit=True))

    with observe_generation("llm_interpret", model="gemini") as generation:
        generation.record(output="응답")


def test_recorder_failure_does_not_break_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)

    class _BrokenSpan(_FakeSpan):
        def update(self, **fields: Any) -> None:
            raise RuntimeError("기록 실패")

    _install(monkeypatch, _FakeClient(_BrokenSpan()))

    with observe_step("scoring") as step:
        step.record(output="무시된다")


# --- 6. 호출부의 예외는 삼키지 않는다 -------------------------------------------


def test_caller_exception_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """관측이 먹어도 되는 건 자기 실패뿐이다.

    `with` 전체를 try로 감싸면 호출부 예외까지 사라진다 — 추천이 실패했는데 성공한
    것처럼 보이는 최악의 형태다.
    """
    _enable(monkeypatch)
    client = _FakeClient()
    _install(monkeypatch, client)

    with pytest.raises(ValueError, match="추천 실패"):
        with observe_step("scoring"):
            raise ValueError("추천 실패")

    # 예외를 관측 객체에도 그대로 전달해야 Langfuse가 실패로 표시한다.
    assert client.observations[0].exited_with is ValueError


def test_caller_exception_survives_a_failing_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """종료가 터져도 호출부 예외가 그걸로 덮이면 안 된다."""
    _enable(monkeypatch)
    _install(monkeypatch, _FakeClient(fail_on_exit=True))

    with pytest.raises(ValueError, match="추천 실패"):
        with observe_step("scoring"):
            raise ValueError("추천 실패")


# --- 7. 기록 값 -----------------------------------------------------------------


def test_recorder_drops_none_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """값이 없는 것과 "None으로 덮어쓴 것"은 다르다."""
    _enable(monkeypatch)
    client = _FakeClient()
    _install(monkeypatch, client)

    with observe_generation("llm_interpret", model="gemini") as generation:
        generation.record(output=None, usage_details=None)
        generation.record(output="응답", usage_details={"input_tokens": 12, "output_tokens": 34})

    assert client.span.updates == [
        {"output": "응답", "usage_details": {"input_tokens": 12, "output_tokens": 34}}
    ]
