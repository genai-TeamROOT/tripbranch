"""Experiment 평가의 판정 규칙을 잠근다.

서버도 Langfuse도 타지 않는다 — evaluator 함수의 판정만 본다. **CSV 경로
(`evaluate_agent_quality`)와 같은 기준이어야 한다**: 두 경로가 같은 골드셋을 읽으므로
판정이 갈리면 어느 수치를 믿어야 하는지 알 수 없게 된다.
"""

from __future__ import annotations

from typing import Any

from scripts.run_langfuse_experiment import (
    MAX_CONCURRENCY,
    case_pass,
    case_pass_rate,
    condition_match,
    intent_match,
    make_task,
)


def _out(intents: list[str], conditions: dict[str, Any]) -> dict[str, Any]:
    return {"turn_intents": intents, "final_conditions": conditions}


def test_intent_order_matters() -> None:
    """순서가 어긋나면 다른 대화다 — 집합으로 비교하면 안 된다."""
    expected = _out(["RECOMMEND", "MODIFY"], {})

    assert (
        intent_match(output=_out(["RECOMMEND", "MODIFY"], {}), expected_output=expected)["value"]
        == 1.0
    )
    assert (
        intent_match(output=_out(["MODIFY", "RECOMMEND"], {}), expected_output=expected)["value"]
        == 0.0
    )


def test_intent_turn_count_mismatch_fails() -> None:
    """턴 수가 다르면 케이스를 다 돌지 못한 것이다."""
    expected = _out(["RECOMMEND", "MODIFY"], {})

    assert intent_match(output=_out(["RECOMMEND"], {}), expected_output=expected)["value"] == 0.0


def test_extra_conditions_are_not_penalized() -> None:
    """기대하지 않은 필드가 더 채워진 것은 감점하지 않는다 — CSV 경로와 같은 규칙."""
    expected = _out([], {"search_center": "경복궁"})
    actual = _out([], {"search_center": "경복궁", "place_tags": ["카페"]})

    assert condition_match(output=actual, expected_output=expected)["value"] == 1.0


def test_missing_condition_field_fails_and_names_it() -> None:
    """어느 필드가 틀렸는지 comment에 남아야 화면에서 바로 읽힌다."""
    expected = _out([], {"search_center": "광화문", "time_available": 240})
    actual = _out([], {"search_center": "광화문", "time_available": 360})

    evaluation = condition_match(output=actual, expected_output=expected)

    assert evaluation["value"] == 0.0
    assert "time_available" in evaluation["comment"]
    assert "search_center" not in evaluation["comment"]


def test_a_case_with_no_expected_conditions_passes() -> None:
    """조건을 기대하지 않는 케이스(GENERAL 등)를 실패로 세면 통과율이 거짓이 된다."""
    assert condition_match(output=_out([], {}), expected_output=_out([], {}))["value"] == 1.0


def test_case_pass_needs_both() -> None:
    expected = _out(["RECOMMEND"], {"search_center": "경복궁"})

    assert (
        case_pass(
            output=_out(["RECOMMEND"], {"search_center": "경복궁"}), expected_output=expected
        )["value"]
        == 1.0
    )
    assert (
        case_pass(output=_out(["MODIFY"], {"search_center": "경복궁"}), expected_output=expected)[
            "value"
        ]
        == 0.0
    )
    assert (
        case_pass(
            output=_out(["RECOMMEND"], {"search_center": "광화문"}), expected_output=expected
        )["value"]
        == 0.0
    )


def test_run_rate_averages_item_evaluations() -> None:
    class _Result:
        def __init__(self, value: float) -> None:
            self.evaluations = [{"name": "case_pass", "value": value}]

    rate = case_pass_rate(item_results=[_Result(1.0), _Result(1.0), _Result(0.0), _Result(1.0)])

    assert rate["value"] == 0.75


def test_run_rate_reads_object_evaluations_too() -> None:
    """SDK가 dict가 아니라 객체를 줄 수도 있다.

    dict만 보면 분모가 0이 되어 **회차 점수가 조용히 0.0으로 찍힌다** — 실제로
    2026-08-26 첫 실행에서 `None: None`이 나온 게 같은 뿌리다.
    """

    class _Evaluation:
        def __init__(self, value: float) -> None:
            self.name = "case_pass"
            self.value = value

    class _Result:
        def __init__(self, value: float) -> None:
            self.evaluations = [_Evaluation(value)]

    rate = case_pass_rate(item_results=[_Result(1.0), _Result(0.0)])

    assert rate["value"] == 0.5


def test_run_rate_is_zero_without_matching_evaluations() -> None:
    """이름이 안 맞으면 0으로 둔다 — 없는 걸 1.0으로 세면 통과율이 거짓이 된다."""

    class _Result:
        evaluations = [{"name": "other", "value": 1.0}]

    assert case_pass_rate(item_results=[_Result()])["value"] == 0.0


def test_task_sends_traceparent_and_keeps_one_session(monkeypatch) -> None:
    """**traceparent가 빠지면 trace가 둘로 갈린다** — 실험 표의 행이 빈 trace가 된다.

    그리고 다중 턴은 같은 session_id로 이어져야 한다. 첫 턴에만 좌표를 넣는 것도
    CSV 경로와 같은 규칙이다.
    """
    sent: list[dict[str, Any]] = []

    class _Response:
        def __init__(self, index: int) -> None:
            self._index = index

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "llm_output": {"intent": "RECOMMEND" if self._index == 0 else "MODIFY"},
                "state": {"session_id": "sess_1", "user_conditions": {"search_center": "경복궁"}},
            }

    class _Client:
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _Response:
            sent.append({"json": json, "headers": headers})
            return _Response(len(sent) - 1)

    import scripts.run_langfuse_experiment as module

    monkeypatch.setattr(module.httpx, "Client", lambda **_: _Client())
    monkeypatch.setattr(module, "_traceparent", lambda: {"traceparent": "00-abc-def-01"})

    item = type(
        "Item",
        (),
        {"input": {"turns": ["경복궁 카페", "미술관으로 바꿔줘"], "device_location": "37.5,126.9"}},
    )()
    output = make_task("http://localhost:8000")(item=item)

    assert output["turn_intents"] == ["RECOMMEND", "MODIFY"]
    assert all(call["headers"]["traceparent"] == "00-abc-def-01" for call in sent)
    assert sent[0]["json"]["session_id"] is None
    assert sent[1]["json"]["session_id"] == "sess_1"
    assert sent[0]["json"]["device_location"] == "37.5,126.9"
    assert "device_location" not in sent[1]["json"]


def test_concurrency_is_one() -> None:
    """골드셋은 다중 턴이라 한 케이스 안 순서가 중요하고, 실 API라 병렬로 올리면 429다.

    `run_experiment`의 기본값은 50이므로 명시적으로 내려둔다.
    """
    assert MAX_CONCURRENCY == 1


def test_the_experiment_client_turns_tracing_on() -> None:
    """**같은 원인으로 세 번 깨졌다.** `_client()`의 기본값은 `tracing_enabled=False`다.

    꺼져 있으면 span을 만드는 기능이 조용히 죽는다.
      · `create_score` → 첫머리에서 return (2026-08-26 Score 41건 소실)
      · `run_experiment` → trace id가 `0000…0`인 run item 3건 (같은 날)
    둘 다 API는 성공을 돌려주고 화면에만 아무것도 안 나왔다. 그래서 원문으로 잠근다.
    """
    import inspect

    import scripts.run_langfuse_experiment as module

    source = inspect.getsource(module.main)

    assert "_client(tracing_enabled=True)" in source
    assert "_client()" not in source
