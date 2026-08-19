"""TripBranch Agent 품질 골드셋을 실행하고 결과를 누적 저장한다.

입력:
    backend/test_results/agent_quality/evaluation_dev.csv
    backend/test_results/agent_quality/evaluation_final.csv

출력(실행마다 새로 생성):
    backend/test_results/agent_quality/runs/<run_id>/case_results.csv
    backend/test_results/agent_quality/runs/<run_id>/intent_metrics.csv
    backend/test_results/agent_quality/runs/<run_id>/confusion_matrix.csv
    backend/test_results/agent_quality/runs/<run_id>/summary.json
    backend/test_results/agent_quality/history.csv  (실행 요약 누적)

호출:
    backend/.venv/bin/python -m scripts.evaluate_agent_quality --split dev
    backend/.venv/bin/python -m scripts.evaluate_agent_quality --split final
    backend/.venv/bin/python -m scripts.evaluate_agent_quality --split all

실제 /api/chat과 Gemini/Tool을 호출하므로 pytest에는 포함하지 않는다. 평가셋의
정답은 자동 생성한 값이 아니라, 팀이 합의해 검토해야 하는 골드 라벨이다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
QUALITY_DIR = ROOT_DIR / "test_results" / "agent_quality"
DATASET_PATHS = {
    "dev": QUALITY_DIR / "evaluation_dev.csv",
    "final": QUALITY_DIR / "evaluation_final.csv",
}
HISTORY_PATH = QUALITY_DIR / "history.csv"
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_INTERVAL_SECONDS = 0.4


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    title: str
    turns: tuple[str, ...]
    expected_turn_intents: tuple[str, ...]
    expected_final_conditions: dict[str, Any]
    device_location: str | None
    note: str


@dataclass(frozen=True)
class CaseResult:
    case: EvaluationCase
    actual_turn_intents: tuple[str, ...]
    actual_final_conditions: dict[str, Any]
    intent_matches: tuple[bool, ...]
    condition_matches: dict[str, bool]
    client_elapsed_ms: float
    server_elapsed_ms: float | None
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and all(self.intent_matches) and all(self.condition_matches.values())


def _parse_json(value: str, *, column: str, case_id: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{case_id}의 {column} JSON이 올바르지 않습니다: {exc.msg}") from exc


def load_cases(split: Literal["dev", "final"]) -> list[EvaluationCase]:
    """CSV 골드셋을 읽고 기본 계약(턴 수·정답 Intent 수)을 검증한다."""

    path = DATASET_PATHS[split]
    if not path.exists():
        raise FileNotFoundError(f"평가셋을 찾을 수 없습니다: {path}")

    cases: list[EvaluationCase] = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            case_id = (row.get("case_id") or "").strip()
            if not case_id:
                raise ValueError(f"{path}에 case_id가 비어 있는 행이 있습니다.")
            turns = _parse_json(row.get("turns") or "[]", column="turns", case_id=case_id)
            intents = _parse_json(
                row.get("expected_turn_intents") or "[]",
                column="expected_turn_intents",
                case_id=case_id,
            )
            conditions = _parse_json(
                row.get("expected_final_conditions") or "{}",
                column="expected_final_conditions",
                case_id=case_id,
            )
            if not isinstance(turns, list) or not all(
                isinstance(turn, str) and turn for turn in turns
            ):
                raise ValueError(f"{case_id}의 turns는 비어 있지 않은 문자열 배열이어야 합니다.")
            if not isinstance(intents, list) or not all(
                isinstance(intent, str) for intent in intents
            ):
                raise ValueError(f"{case_id}의 expected_turn_intents는 문자열 배열이어야 합니다.")
            if len(turns) != len(intents):
                raise ValueError(
                    f"{case_id}: turns {len(turns)}개와 expected_turn_intents "
                    f"{len(intents)}개가 다릅니다."
                )
            if not isinstance(conditions, dict):
                raise ValueError(f"{case_id}의 expected_final_conditions는 JSON 객체여야 합니다.")

            cases.append(
                EvaluationCase(
                    case_id=case_id,
                    title=(row.get("title") or case_id).strip(),
                    turns=tuple(turns),
                    expected_turn_intents=tuple(intents),
                    expected_final_conditions=conditions,
                    device_location=(row.get("device_location") or "").strip() or None,
                    note=(row.get("note") or "").strip(),
                )
            )
    return cases


def dataset_digest(cases: list[EvaluationCase]) -> str:
    """동일 골드셋끼리만 전 실행과 비교하도록 안정적인 해시를 만든다."""

    payload = [
        {
            "case_id": case.case_id,
            "turns": case.turns,
            "expected_turn_intents": case.expected_turn_intents,
            "expected_final_conditions": case.expected_final_conditions,
        }
        for case in cases
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:12]


def _intent(body: dict[str, Any]) -> str:
    output = body.get("llm_output")
    return str(output.get("intent", "")) if isinstance(output, dict) else ""


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


def _server_elapsed_ms(body: dict[str, Any]) -> float | None:
    recommendations = body.get("recommendations")
    if isinstance(recommendations, dict) and isinstance(
        recommendations.get("elapsed_ms"), (int, float)
    ):
        return float(recommendations["elapsed_ms"])
    schedule = body.get("schedule")
    if isinstance(schedule, dict) and isinstance(schedule.get("elapsed_ms"), (int, float)):
        return float(schedule["elapsed_ms"])
    return None


def _post(
    client: httpx.Client, base_url: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = client.post(f"{base_url}/api/chat", json=payload)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if response.is_error:
        try:
            detail: Any = response.json()
        except ValueError:
            detail = response.text[:500]
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("/api/chat 응답이 JSON 객체가 아닙니다.")
    return body, elapsed_ms


def evaluate_case(client: httpx.Client, case: EvaluationCase, base_url: str) -> CaseResult:
    """한 케이스의 턴을 같은 session_id로 순서대로 실행한다."""

    started = time.perf_counter()
    session_id: str | None = None
    response: dict[str, Any] | None = None
    actual_intents: list[str] = []
    try:
        for turn_index, user_input in enumerate(case.turns):
            payload: dict[str, Any] = {"user_input": user_input, "session_id": session_id}
            # 위치가 필요한 추천·일정 케이스도 재현 가능하게 첫 턴에만 고정 좌표를 넣는다.
            if turn_index == 0 and case.device_location:
                payload["device_location"] = case.device_location
            response, _ = _post(client, base_url, payload)
            actual_intents.append(_intent(response))
            session_id = _session_id(response)
            if session_id is None:
                raise ValueError(f"{turn_index + 1}턴 응답에 session_id가 없습니다.")

        assert response is not None
        final_conditions = _conditions(response)
        condition_matches = {
            field: final_conditions.get(field) == expected
            for field, expected in case.expected_final_conditions.items()
        }
        return CaseResult(
            case=case,
            actual_turn_intents=tuple(actual_intents),
            actual_final_conditions=final_conditions,
            intent_matches=tuple(
                actual == expected
                for actual, expected in zip(actual_intents, case.expected_turn_intents, strict=True)
            ),
            condition_matches=condition_matches,
            client_elapsed_ms=(time.perf_counter() - started) * 1000,
            server_elapsed_ms=_server_elapsed_ms(response),
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        return CaseResult(
            case=case,
            actual_turn_intents=tuple(actual_intents),
            actual_final_conditions=_conditions(response) if response else {},
            intent_matches=tuple(False for _ in case.expected_turn_intents),
            condition_matches={field: False for field in case.expected_final_conditions},
            client_elapsed_ms=(time.perf_counter() - started) * 1000,
            server_elapsed_ms=_server_elapsed_ms(response) if response else None,
            error=str(exc),
        )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def intent_metrics(results: list[CaseResult]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """모든 턴을 표본으로 Accuracy·Intent별 P/R/F1·Macro F1을 계산한다."""

    pairs = [
        (expected, actual)
        for result in results
        for expected, actual in zip(
            result.case.expected_turn_intents,
            result.actual_turn_intents
            + ("__ERROR__",)
            * (len(result.case.expected_turn_intents) - len(result.actual_turn_intents)),
            strict=True,
        )
    ]
    labels = sorted({expected for expected, _ in pairs} | {actual for _, actual in pairs})
    per_intent: list[dict[str, Any]] = []
    for label in labels:
        true_positive = sum(expected == label and actual == label for expected, actual in pairs)
        false_positive = sum(expected != label and actual == label for expected, actual in pairs)
        false_negative = sum(expected == label and actual != label for expected, actual in pairs)
        precision = _ratio(true_positive, true_positive + false_positive)
        recall = _ratio(true_positive, true_positive + false_negative)
        f1 = _ratio(2 * precision * recall, precision + recall)
        per_intent.append(
            {
                "intent": label,
                "support": sum(expected == label for expected, _ in pairs),
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )
    expected_labels = {expected for expected, _ in pairs}
    expected_metrics = [row for row in per_intent if row["intent"] in expected_labels]
    metric = {
        "turn_count": len(pairs),
        "intent_accuracy": _ratio(
            sum(expected == actual for expected, actual in pairs), len(pairs)
        ),
        "macro_precision": statistics.fmean(row["precision"] for row in expected_metrics)
        if expected_metrics
        else 0.0,
        "macro_recall": statistics.fmean(row["recall"] for row in expected_metrics)
        if expected_metrics
        else 0.0,
        "macro_f1": statistics.fmean(row["f1"] for row in expected_metrics)
        if expected_metrics
        else 0.0,
    }
    return metric, per_intent


def build_summary(results: list[CaseResult]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Intent와 조건·다중턴·지연시간 지표를 하나의 실행 요약으로 만든다."""

    intents, per_intent = intent_metrics(results)
    checks = [matched for result in results for matched in result.condition_matches.values()]
    exact_condition_cases = [result for result in results if result.case.expected_final_conditions]
    multi_turn = [result for result in results if len(result.case.turns) > 1]
    field_scores: dict[str, list[bool]] = {}
    for result in results:
        for field, matched in result.condition_matches.items():
            field_scores.setdefault(field, []).append(matched)
    elapsed = [result.client_elapsed_ms for result in results]
    summary = {
        **intents,
        "case_count": len(results),
        "case_pass_rate": _ratio(sum(result.passed for result in results), len(results)),
        "condition_field_accuracy": _ratio(sum(checks), len(checks)),
        "condition_exact_match_rate": _ratio(
            sum(all(result.condition_matches.values()) for result in exact_condition_cases),
            len(exact_condition_cases),
        ),
        "multi_turn_case_pass_rate": _ratio(
            sum(result.passed for result in multi_turn), len(multi_turn)
        ),
        "error_count": sum(bool(result.error) for result in results),
        "client_latency_p50_ms": percentile(elapsed, 0.50),
        "client_latency_p95_ms": percentile(elapsed, 0.95),
        "condition_accuracy_by_field": {
            field: _ratio(sum(values), len(values))
            for field, values in sorted(field_scores.items())
        },
    }
    return summary, per_intent


def percentile(values: list[float], quantile: float) -> float:
    """외부 의존성 없이 선형 보간 p50/p95를 계산한다."""

    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return round(ordered[lower], 2)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower), 2)


def confusion_rows(results: list[CaseResult]) -> tuple[list[str], list[dict[str, int]]]:
    pairs = [
        (expected, actual)
        for result in results
        for expected, actual in zip(
            result.case.expected_turn_intents,
            result.actual_turn_intents
            + ("__ERROR__",)
            * (len(result.case.expected_turn_intents) - len(result.actual_turn_intents)),
            strict=True,
        )
    ]
    labels = sorted({value for pair in pairs for value in pair})
    matrix = Counter(pairs)
    return labels, [
        {"expected": expected, **{actual: matrix[expected, actual] for actual in labels}}
        for expected in labels
    ]


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def write_run(
    *,
    run_dir: Path,
    results: list[CaseResult],
    summary: dict[str, Any],
    per_intent: list[dict[str, Any]],
) -> None:
    """상세·혼동행렬·요약을 한 실행 폴더에 분리 저장한다."""

    _write_csv(
        run_dir / "case_results.csv",
        [
            "case_id",
            "title",
            "turns",
            "expected_turn_intents",
            "actual_turn_intents",
            "intent_match",
            "expected_final_conditions",
            "actual_final_conditions",
            "condition_matches",
            "case_pass",
            "client_elapsed_ms",
            "server_elapsed_ms",
            "note",
            "error",
        ],
        [
            [
                result.case.case_id,
                result.case.title,
                json.dumps(result.case.turns, ensure_ascii=False),
                json.dumps(result.case.expected_turn_intents, ensure_ascii=False),
                json.dumps(result.actual_turn_intents, ensure_ascii=False),
                json.dumps(result.intent_matches, ensure_ascii=False),
                json.dumps(result.case.expected_final_conditions, ensure_ascii=False),
                json.dumps(result.actual_final_conditions, ensure_ascii=False),
                json.dumps(result.condition_matches, ensure_ascii=False),
                result.passed,
                round(result.client_elapsed_ms, 2),
                result.server_elapsed_ms,
                result.case.note,
                result.error,
            ]
            for result in results
        ],
    )
    _write_csv(
        run_dir / "intent_metrics.csv",
        ["intent", "support", "precision", "recall", "f1"],
        [
            [
                row["intent"],
                row["support"],
                round(row["precision"], 4),
                round(row["recall"], 4),
                round(row["f1"], 4),
            ]
            for row in per_intent
        ],
    )
    labels, matrix_rows = confusion_rows(results)
    _write_csv(
        run_dir / "confusion_matrix.csv",
        ["expected\\actual", *labels],
        [[row["expected"], *[row[label] for label in labels]] for row in matrix_rows],
    )
    with (run_dir / "summary.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)

    write_markdown_report(
        run_dir=run_dir,
        results=results,
        summary=summary,
        per_intent=per_intent,
        labels=labels,
        matrix_rows=matrix_rows,
    )


def _percent(value: float) -> str:
    return f"{value:.1%}"


def write_markdown_report(
    *,
    run_dir: Path,
    results: list[CaseResult],
    summary: dict[str, Any],
    per_intent: list[dict[str, Any]],
    labels: list[str],
    matrix_rows: list[dict[str, int]],
) -> None:
    """JSON/CSV 수치를 발표·리뷰에서 바로 읽을 수 있는 Markdown으로 요약한다."""

    lines = [
        "# Agent 품질 평가 결과",
        "",
        f"- 실행 ID: `{summary['run_id']}`",
        f"- 실행 시각: {summary['created_at']}",
        f"- 프롬프트 기준선: `{summary.get('prompt_variant', 'current')}`",
        f"- 평가셋: `{summary['split']}` · {summary['case_count']}건 / {summary['turn_count']}턴",
        f"- 골드셋 해시: `{summary['dataset_digest']}`",
        "",
        "## 핵심 결과",
        "",
        "| 지표 | 결과 | 의미 |",
        "| --- | ---: | --- |",
        (
            f"| Intent Accuracy | {_percent(summary['intent_accuracy'])} | "
            "전체 턴에서 Intent가 일치한 비율 |"
        ),
        (
            f"| Intent Macro F1 | {summary['macro_f1']:.3f} | "
            "Intent별 F1을 동등하게 평균낸 균형 점수 |"
        ),
        (
            f"| 조건 필드 정확도 | {_percent(summary['condition_field_accuracy'])} | "
            "기대 조건 필드 하나하나가 일치한 비율 |"
        ),
        (
            f"| 최종 조건 완전 일치율 | {_percent(summary['condition_exact_match_rate'])} | "
            "조건을 기대한 케이스에서 모든 필드가 맞은 비율 |"
        ),
        (
            f"| 멀티턴 통과율 | {_percent(summary['multi_turn_case_pass_rate'])} | "
            "2턴 이상 케이스가 Intent·조건을 모두 통과한 비율 |"
        ),
        (
            f"| 전체 케이스 통과율 | {_percent(summary['case_pass_rate'])} | "
            "케이스 단위로 모든 검증을 통과한 비율 |"
        ),
        f"| API 오류 | {summary['error_count']}건 | HTTP/Provider 오류로 평가하지 못한 케이스 수 |",
        "",
        "## 실행 성능",
        "",
        "| 지표 | 결과 |",
        "| --- | ---: |",
        f"| 클라이언트 지연시간 p50 | {summary['client_latency_p50_ms'] / 1000:.2f}초 |",
        f"| 클라이언트 지연시간 p95 | {summary['client_latency_p95_ms'] / 1000:.2f}초 |",
        "",
        "## Intent별 Precision / Recall / F1",
        "",
        "| Intent | 표본 수 | Precision | Recall | F1 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {row['intent']} | {row['support']} | {_percent(row['precision'])} | "
        f"{_percent(row['recall'])} | {row['f1']:.3f} |"
        for row in per_intent
    )

    lines.extend(
        [
            "",
            "## 혼동행렬",
            "",
            "행은 **기대 Intent**, 열은 **실제 Intent**입니다. 대각선 값은 정분류이고, "
            "대각선 밖 값은 어떤 Intent끼리 혼동했는지 보여줍니다.",
            "",
            "| 기대 \\ 실제 | " + " | ".join(labels) + " |",
            "| --- | " + " | ".join("---:" for _ in labels) + " |",
        ]
    )
    lines.extend(
        f"| {row['expected']} | " + " | ".join(str(row[label]) for label in labels) + " |"
        for row in matrix_rows
    )

    lines.extend(["", "## 조건 필드별 정확도", "", "| 필드 | 정확도 |", "| --- | ---: |"])
    lines.extend(
        f"| {field} | {_percent(score)} |"
        for field, score in summary["condition_accuracy_by_field"].items()
    )

    failed = [result for result in results if not result.passed]
    lines.extend(["", "## 불일치·오류 케이스", ""])
    if not failed:
        lines.append("모든 케이스가 Intent와 기대 조건을 통과했습니다.")
    else:
        for result in failed:
            mismatches = [
                f"`{field}` 기대 `{result.case.expected_final_conditions[field]!r}` / "
                f"실제 `{result.actual_final_conditions.get(field)!r}`"
                for field, matched in result.condition_matches.items()
                if not matched
            ]
            lines.extend(
                [
                    f"### {result.case.case_id} — {result.case.title}",
                    "",
                    f"- 기대 Intent: `{', '.join(result.case.expected_turn_intents)}`",
                    f"- 실제 Intent: `{', '.join(result.actual_turn_intents) or '__ERROR__'}`",
                    f"- 조건 불일치: {', '.join(mismatches) if mismatches else '없음'}",
                    f"- 오류: {result.error or '없음'}",
                    "",
                ]
            )

    if summary.get("previous_run_id"):
        lines.extend(
            [
                "## 직전 동일 골드셋 대비",
                "",
                f"비교 대상: `{summary['previous_run_id']}`",
                "",
            ]
        )
        for metric, delta in summary.get("delta_from_previous", {}).items():
            lines.append(f"- {metric}: {delta:+.4f}")

    lines.extend(
        [
            "",
            "## 원본 파일",
            "",
            "- `summary.json`: 기계 처리용 전체 요약",
            "- `case_results.csv`: 케이스별 기대값·실제값·조건 비교",
            "- `intent_metrics.csv`: Intent별 Precision / Recall / F1",
            "- `confusion_matrix.csv`: 혼동행렬 원본",
        ]
    )
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_history() -> list[dict[str, str]]:
    if not HISTORY_PATH.exists():
        return []
    with HISTORY_PATH.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def append_history(summary: dict[str, Any]) -> dict[str, str] | None:
    """동일 split·골드셋 해시의 직전 실행과 비교할 수 있도록 요약을 누적한다."""

    previous = next(
        (
            row
            for row in reversed(_read_history())
            if row.get("split") == summary["split"]
            and row.get("dataset_digest") == summary["dataset_digest"]
            and row.get("prompt_variant", "current") == summary["prompt_variant"]
        ),
        None,
    )
    header = [
        "run_id",
        "created_at",
        "split",
        "dataset_digest",
        "prompt_variant",
        "case_count",
        "turn_count",
        "intent_accuracy",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "condition_field_accuracy",
        "condition_exact_match_rate",
        "multi_turn_case_pass_rate",
        "case_pass_rate",
        "error_count",
        "client_latency_p50_ms",
        "client_latency_p95_ms",
    ]
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    exists = HISTORY_PATH.exists()
    with HISTORY_PATH.open("a", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow({key: summary.get(key, "") for key in header})
    return previous


def _previous_delta(summary: dict[str, Any], previous: dict[str, str] | None) -> dict[str, float]:
    if previous is None:
        return {}
    delta: dict[str, float] = {}
    for key in ("intent_accuracy", "macro_f1", "condition_field_accuracy", "case_pass_rate"):
        try:
            delta[key] = round(float(summary[key]) - float(previous[key]), 4)
        except (KeyError, TypeError, ValueError):
            continue
    return delta


def _check_server(client: httpx.Client, base_url: str) -> None:
    for path in ("/health", "/api/health"):
        try:
            response = client.get(f"{base_url}{path}", timeout=5.0)
            if response.is_success:
                return
        except httpx.HTTPError:
            continue
    raise RuntimeError(f"서버({base_url})에 연결할 수 없습니다. backend 서버를 먼저 실행해주세요.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TripBranch Agent 골드셋 평가")
    parser.add_argument("--split", choices=("dev", "final", "all"), default="dev")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--prompt-variant",
        default="current",
        help=(
            "평가 중인 서버의 TRIPBRANCH_PROMPT_VARIANT 값. 서버 설정을 바꾸지는 않고 "
            "결과 식별·비교에만 사용한다."
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--limit", type=int, default=None, help="점검용으로 앞 N개 케이스만 실행")
    parser.add_argument(
        "--dry-run", action="store_true", help="API를 호출하지 않고 CSV 계약·건수만 검증"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    splits: tuple[Literal["dev", "final"], ...] = (
        ("dev", "final") if args.split == "all" else (args.split,)
    )
    for split in splits:
        cases = load_cases(split)
        if args.limit is not None:
            cases = cases[: args.limit]
        digest = dataset_digest(cases)
        print(f"[{split}] 골드셋 {len(cases)}건 · digest={digest}")
        if args.dry_run:
            continue

        started_at = datetime.now().astimezone()
        variant_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", args.prompt_variant).strip("-")
        run_id = (
            f"{started_at.strftime('%Y-%m-%d_%H%M')}_{split}_{variant_slug}_"
            f"{len(cases)}cases_{digest}"
        )
        run_dir = QUALITY_DIR / "runs" / run_id
        results: list[CaseResult] = []
        with httpx.Client(timeout=args.timeout_seconds) as client:
            _check_server(client, args.base_url.rstrip("/"))
            for index, case in enumerate(cases, start=1):
                result = evaluate_case(client, case, args.base_url.rstrip("/"))
                results.append(result)
                print(
                    f"[{split} {index:>2}/{len(cases)}] {'PASS' if result.passed else 'FAIL'} "
                    f"{case.case_id} · {result.client_elapsed_ms / 1000:.1f}s"
                )
                if result.error:
                    print(f"  오류: {result.error}")
                if index < len(cases):
                    time.sleep(args.interval_seconds)

        summary, per_intent = build_summary(results)
        summary.update(
            {
                "run_id": run_id,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "split": split,
                "dataset_digest": digest,
                "prompt_variant": args.prompt_variant,
            }
        )
        previous = append_history(summary)
        summary["previous_run_id"] = previous.get("run_id") if previous else None
        summary["delta_from_previous"] = _previous_delta(summary, previous)
        write_run(run_dir=run_dir, results=results, summary=summary, per_intent=per_intent)
        print(
            f"  Intent Accuracy={summary['intent_accuracy']:.1%} · "
            f"Macro F1={summary['macro_f1']:.3f} · "
            f"조건 필드 정확도={summary['condition_field_accuracy']:.1%}"
        )
        if summary["delta_from_previous"]:
            print(f"  직전 동일 골드셋 대비: {summary['delta_from_previous']}")
        print(f"  결과: {run_dir}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"평가를 실행하지 못했습니다: {exc}", file=sys.stderr)
        sys.exit(1)
