"""다중 턴 골드셋을 Langfuse Experiment로 돌린다.

배경: `evaluate_agent_quality`가 CSV로 결과를 남기고, `push_langfuse_dataset_run`이
      그걸 사후에 Langfuse로 올렸다. 그런데 **그 업로드 경로가 폐지된 v3 API였다** —
      화면의 Runs 탭 자체가 없어졌고 Experiments가 그 자리를 대신한다
      (2026-08-26 확인: `datasets.get_runs`·`dataset_run_items.list`가
      `Langfuse v3 is deprecated` 를 돌려준다). Experiments는 **trace에 실린 실험
      속성**으로 그려지므로, 사후 업로드로는 만들 수 없다.

      그래서 방향을 뒤집는다. 평가를 **Langfuse가 주도**하게 하고, 우리 서버는 그
      trace 안에서 불린다.

방법: `client.run_experiment()`가 Dataset 항목마다 `task`를 부른다. `task`는 한
      케이스의 턴을 순서대로 `/api/chat`에 보내는데, **`traceparent` 헤더를 함께
      싣는다.** 서버 미들웨어(`main.py::join_incoming_trace`)가 그걸 받아 자기 span을
      실험 trace의 자식으로 만든다. 그래서 실험 표의 한 행을 누르면
      `classify_intent`·`scoring`까지 그 안에 다 들어 있다.

      **CSV를 대체하지 않는다.** `evaluate_agent_quality`는 그대로 남는다 — 관측이
      죽어도 평가는 돌아야 하고, CSV는 git에 남아 PR에서 diff로 읽힌다. 이쪽은
      화면에서 보기 위한 경로다. 두 경로가 같은 골드셋을 읽으므로 수치는 맞아야 한다.

판정 기준 — 합격/불합격:
  * Intent는 턴 순서까지 같아야 맞는 것으로 센다. 순서가 어긋나면 다른 대화다.
  * 조건은 **기대한 필드만** 본다. 기대하지 않은 필드가 더 채워진 것은 감점하지 않는다
    (`evaluate_agent_quality`와 같은 규칙 — 두 경로의 수치가 갈리면 안 된다).
  * 한 턴이라도 HTTP가 실패하면 그 케이스는 실패로 남기고 계속 간다. 한 건 때문에
    회차 전체를 버리지 않는다.

실행: 서버를 먼저 띄운다(LANGFUSE_ENABLED=true, APP_ENV=local).
      cd backend && .venv/bin/python -m scripts.run_langfuse_experiment --split dev
      cd backend && .venv/bin/python -m scripts.run_langfuse_experiment --split dev --limit 3

주의: `--split final`은 변경 직전에만 돌린다. 최종셋 결과를 보고 프롬프트를 다시
      조정하면 평가 과적합이다.

      **동시 실행 수를 1로 둔다.** 골드셋은 다중 턴이라 한 케이스 안에서 순서가
      중요하고, 실 LLM·외부 API를 치므로 병렬로 올리면 429가 난다.
"""

from __future__ import annotations

import argparse
from typing import Any, Final

import httpx
from langfuse.experiment import Evaluation

from app.config import settings
from scripts.sync_langfuse_dataset import DATASET_NAMES, _client

DEFAULT_BASE_URL: Final = "http://localhost:8000"
# run_experiment의 기본값은 50이다. 다중 턴 + 실 API라 1로 내린다(모듈 docstring).
MAX_CONCURRENCY: Final = 1


def _traceparent() -> dict[str, str]:
    """지금 열려 있는 span을 가리키는 헤더.

    이게 있어야 서버 span이 실험 trace의 자식이 된다. 없으면 trace가 둘로 갈려서
    실험 표의 행을 눌러도 내부 span이 없는 빈 trace가 열린다.
    """
    try:
        from opentelemetry.propagate import inject

        headers: dict[str, str] = {}
        inject(headers)
        return headers
    except Exception:
        return {}


def _intent(body: dict[str, Any]) -> str:
    llm_output = body.get("llm_output")
    if isinstance(llm_output, dict) and isinstance(llm_output.get("intent"), str):
        return llm_output["intent"]
    return ""


def _conditions(body: dict[str, Any]) -> dict[str, Any]:
    state = body.get("state")
    if not isinstance(state, dict):
        return {}
    conditions = state.get("user_conditions")
    return conditions if isinstance(conditions, dict) else {}


def _session_id(body: dict[str, Any]) -> str | None:
    state = body.get("state")
    if not isinstance(state, dict):
        return None
    value = state.get("session_id")
    return value if isinstance(value, str) and value else None


def make_task(base_url: str) -> Any:
    """한 케이스의 턴을 순서대로 서버에 보내는 `task`를 만든다."""

    def task(*, item: Any, **_: Any) -> dict[str, Any]:
        payload_input = item.input if hasattr(item, "input") else item["input"]
        turns = payload_input["turns"]
        device_location = payload_input.get("device_location")

        session_id: str | None = None
        body: dict[str, Any] = {}
        intents: list[str] = []
        with httpx.Client(timeout=120.0) as client:
            for index, user_input in enumerate(turns):
                request: dict[str, Any] = {"user_input": user_input, "session_id": session_id}
                # 위치가 필요한 케이스도 재현되게 첫 턴에만 고정 좌표를 넣는다
                # (`evaluate_agent_quality`와 같은 규칙).
                if index == 0 and device_location:
                    request["device_location"] = device_location
                response = client.post(f"{base_url}/api/chat", json=request, headers=_traceparent())
                response.raise_for_status()
                body = response.json()
                intents.append(_intent(body))
                session_id = _session_id(body)
                if session_id is None:
                    raise ValueError(f"{index + 1}턴 응답에 session_id가 없다")

        return {"turn_intents": intents, "final_conditions": _conditions(body)}

    return task


def intent_match(*, output: Any, expected_output: Any, **_: Any) -> Evaluation:
    """턴 순서까지 같아야 맞는 것으로 센다 — 순서가 어긋나면 다른 대화다."""
    expected = list((expected_output or {}).get("turn_intents") or [])
    actual = list((output or {}).get("turn_intents") or [])
    return Evaluation(
        name="intent_match",
        value=1.0 if expected and expected == actual else 0.0,
        comment=f"기대 {expected} · 실제 {actual}",
        data_type="NUMERIC",
    )


def condition_match(*, output: Any, expected_output: Any, **_: Any) -> Evaluation:
    """**기대한 필드만** 본다. 더 채워진 것은 감점하지 않는다.

    `evaluate_agent_quality`와 같은 규칙이다 — 두 경로가 같은 골드셋을 읽으므로
    판정이 갈리면 어느 수치를 믿어야 하는지 알 수 없게 된다.
    """
    expected = (expected_output or {}).get("final_conditions") or {}
    actual = (output or {}).get("final_conditions") or {}
    if not expected:
        return Evaluation(
            name="condition_match", value=1.0, comment="기대 조건 없음", data_type="NUMERIC"
        )
    wrong = [field for field, want in expected.items() if actual.get(field) != want]
    return Evaluation(
        name="condition_match",
        value=1.0 if not wrong else 0.0,
        comment="일치" if not wrong else f"불일치 {wrong}",
        data_type="NUMERIC",
    )


def case_pass(*, output: Any, expected_output: Any, **_: Any) -> Evaluation:
    """Intent와 조건을 모두 통과했나 — CSV의 `case_pass`와 같은 기준.

    `BOOLEAN`으로 올린다 — 화면에서 통과/실패 막대가 되고, NUMERIC이면 연속값
    평균으로 잡혀 "0.5건 통과" 같은 눈금이 생긴다(`record_score`와 같은 이유).
    """
    both = (
        _field(intent_match(output=output, expected_output=expected_output), "value") == 1.0
        and _field(condition_match(output=output, expected_output=expected_output), "value") == 1.0
    )
    return Evaluation(name="case_pass", value=both, data_type="BOOLEAN")


def _run_rate(item_results: Any, name: str) -> float:
    """항목별 평가에서 이름이 맞는 값만 평균낸다.

    `_field`를 쓰는 이유는 dict/객체 둘 다 오기 때문이다 — 한쪽만 보면 분모가 0이
    되어 회차 점수가 조용히 0.0으로 찍힌다.
    """
    values = [
        _field(evaluation, "value")
        for result in item_results
        for evaluation in (getattr(result, "evaluations", None) or [])
        if _field(evaluation, "name") == name
    ]
    numbers = [float(value) for value in values if isinstance(value, (int, float))]
    return sum(numbers) / len(numbers) if numbers else 0.0


def case_pass_rate(*, item_results: Any, **_: Any) -> Evaluation:
    return Evaluation(
        name="case_pass_rate",
        value=_run_rate(item_results, "case_pass"),
        data_type="NUMERIC",
    )


def intent_accuracy(*, item_results: Any, **_: Any) -> Evaluation:
    """케이스 단위다 — CSV의 `intent_accuracy`(턴 단위)와 이름이 같지만 분모가 다르다.

    그래서 이름을 달리 붙인다. 같은 이름으로 올리면 두 수치가 한 곡선에 섞인다.
    """
    return Evaluation(
        name="case_intent_match_rate",
        value=_run_rate(item_results, "intent_match"),
        data_type="NUMERIC",
    )


def _field(evaluation: Any, key: str) -> Any:
    """평가 결과에서 값 하나를 꺼낸다.

    SDK가 dict를 돌려줄 때도, 속성을 가진 객체를 돌려줄 때도 있다. 한쪽만 보면
    **조용히 `None`이 찍힌다** — 2026-08-26 첫 실행에서 회차 점수가 `None: None`으로
    나온 게 이 때문이다. 값이 실제로는 들어가 있었다.
    """
    if isinstance(evaluation, dict):
        return evaluation.get(key)
    return getattr(evaluation, key, None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=("dev", "final"), default="dev")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--limit", type=int, default=None, help="앞 N건만 (점검용)")
    parser.add_argument("--run-name", default=None, help="회차 이름(생략하면 SDK가 시각을 붙임)")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if settings.app_env != "local":
        print(f"✗ APP_ENV={settings.app_env} — 서버가 traceparent를 받지 않는다(로컬 전용).")
        return 1
    if not settings.langfuse_enabled:
        print("✗ LANGFUSE_ENABLED=false — 실험 trace가 남지 않는다.")
        return 1

    # **span을 만들어야 하므로 켜서 받는다.** 기본값(False)으로 받으면 run item의
    # trace id가 `0000…0`으로 들어가고 실험 표의 행이 빈 껍데기가 된다.
    client = _client(tracing_enabled=True)
    if client is None:
        return 1

    try:
        httpx.get(f"{args.base_url}/api/health", timeout=5.0).raise_for_status()
    except httpx.HTTPError:
        print(f"✗ 서버({args.base_url})에 연결할 수 없다. 먼저 실행한다.")
        return 1

    dataset_name = DATASET_NAMES[args.split]
    items = client.get_dataset(dataset_name).items
    if args.limit:
        items = items[: args.limit]
    print(f"✓ {dataset_name} {len(items)}건")

    result = client.run_experiment(
        name=f"{args.split} 골드셋 회귀",
        run_name=args.run_name,
        description=f"{dataset_name} {len(items)}건 · env={settings.app_env}",
        data=items,
        task=make_task(args.base_url),
        evaluators=[intent_match, condition_match, case_pass],
        run_evaluators=[case_pass_rate, intent_accuracy],
        max_concurrency=MAX_CONCURRENCY,
        metadata={"split": args.split, "source": "run_langfuse_experiment"},
    )
    client.flush()

    print(f"\n회차: {result.run_name}")
    for evaluation in getattr(result, "run_evaluations", None) or []:
        # SDK가 dict를 줄 때도 객체를 줄 때도 있다 — 둘 다 받는다.
        name = _field(evaluation, "name")
        value = _field(evaluation, "value")
        print(f"  {name}: {value}")
    url = getattr(result, "dataset_run_url", None)
    if url:
        print(f"\n{url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
