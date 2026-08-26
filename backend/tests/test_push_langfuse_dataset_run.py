"""평가 1회차를 Dataset Run으로 올리는 도구의 계약을 잠근다.

네트워크를 타지 않는다 — 가짜 클라이언트로 `push_run`이 **무엇을 어떤 모양으로**
부르는지만 본다. 실제 전송은 `--push --yes`가 사람 확인을 받고 하는 일이다.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import pytest

import scripts.push_langfuse_dataset_run as push_langfuse_dataset_run
from scripts.push_langfuse_dataset_run import (
    RUN_SCORES,
    load_run,
    push_run,
    run_metadata,
)

_HEADER = [
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
    "langfuse_trace_ids",
    "note",
    "error",
]


def _row(case_id: str, *, trace_ids: list[str], passed: bool = True) -> list[Any]:
    return [
        case_id,
        f"{case_id} 제목",
        json.dumps(["발화"] * max(len(trace_ids), 1), ensure_ascii=False),
        '["RECOMMEND"]',
        '["RECOMMEND"]',
        "[true]",
        "{}",
        "{}",
        "{}",
        passed,
        1.0,
        2.0,
        json.dumps(trace_ids),
        "",
        "",
    ]


def _write_run(
    tmp_path: Path, rows: list[list[Any]], *, split: str = "dev", header: list[str] = _HEADER
) -> Path:
    run_dir = tmp_path / "2026-08-26_1200_dev_current_35cases_2d4e276eed53"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "split": split,
                "created_at": "2026-08-26T12:00:00+09:00",
                "dataset_digest": "2d4e276eed53",
                "prompt_variant": "current",
                "intent_accuracy": 0.96,
                "case_pass_rate": 0.83,
                "error_count": 2,
                "client_latency_p50_ms": 8855.14,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (run_dir / "case_results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    return run_dir


class _FakeRunItems:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **fields: Any) -> None:
        self.calls.append(fields)


class _FakeDatasets:
    def get_run(self, *, dataset_name: str, run_name: str) -> Any:
        return type("Run", (), {"id": f"runid::{dataset_name}::{run_name}"})()


class _FakeScores:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **fields: Any) -> None:
        self.calls.append(fields)


class _FakeClient:
    """실제 클라이언트와 **같은 자리에** 메서드를 둔다.

    `create_score`는 일부러 두지 않는다 — 그걸 부르면 여기서 AttributeError로
    터져야 한다. SDK의 `create_score`는 `tracing_enabled=False`면 조용히 return
    하므로, 가짜가 그걸 받아주면 테스트는 통과하고 실제로는 아무것도 안 올라간다.
    """

    def __init__(self) -> None:
        self.api = type(
            "Api",
            (),
            {
                "dataset_run_items": _FakeRunItems(),
                "datasets": _FakeDatasets(),
                "scores": _FakeScores(),
            },
        )()

    @property
    def scores(self) -> list[dict[str, Any]]:
        return self.api.scores.calls


def test_last_turn_is_the_linked_trace(tmp_path: Path) -> None:
    """케이스 하나에 trace 하나만 붙는다 — 같은 (run, item)은 덮어쓰기다(실측).

    마지막 턴을 고르는 이유는 `expected_final_conditions`가 그 턴의 결과라서다.
    나머지 턴도 버리지 않는다 — metadata가 아니라 `turn_trace_ids`로 남는다.
    """
    run_dir = _write_run(tmp_path, [_row("DEV-014", trace_ids=["t1", "t2"])])

    payload = load_run(run_dir)

    assert len(payload.links) == 1
    link = payload.links[0]
    assert link.trace_id == "t2"
    assert link.turn_trace_ids == ("t1", "t2")
    assert link.turn_count == 2


def test_item_id_is_namespaced_by_dataset(tmp_path: Path) -> None:
    """항목 id는 프로젝트 전역이라 `case_id` 맨몸으로 쓰면 남의 데이터셋과 부딪힌다."""
    run_dir = _write_run(tmp_path, [_row("DEV-001", trace_ids=["t1"])])

    payload = load_run(run_dir)

    assert payload.links[0].dataset_item_id == "agent-quality-dev-DEV-001"
    assert payload.dataset_name == "agent-quality-dev"


def test_cases_without_a_trace_are_skipped_not_linked(tmp_path: Path) -> None:
    """관측이 꺼진 채로 돈 케이스는 연결할 게 없다. 조용히 빼지 않고 세어서 보고한다."""
    run_dir = _write_run(
        tmp_path,
        [_row("DEV-001", trace_ids=["t1"]), _row("DEV-002", trace_ids=[])],
    )

    payload = load_run(run_dir)

    assert [link.case_id for link in payload.links] == ["DEV-001"]
    assert payload.skipped == ["DEV-002"]


def test_a_run_without_the_trace_column_is_rejected(tmp_path: Path) -> None:
    """trace id를 남기기 전에 돌린 실행이다. 빈 Run을 만들면 집계가 더러워진다."""
    header = [name for name in _HEADER if name != "langfuse_trace_ids"]
    rows = [
        [
            value
            for name, value in zip(_HEADER, _row("DEV-001", trace_ids=["t1"]), strict=True)
            if name != "langfuse_trace_ids"
        ]
    ]
    run_dir = _write_run(tmp_path, rows, header=header)

    with pytest.raises(ValueError, match="langfuse_trace_ids"):
        load_run(run_dir)


def test_goldset_digest_travels_with_the_run(tmp_path: Path) -> None:
    """Dataset이 나중에 갱신되면, 이 회차가 무엇으로 잰 수치인지 알 방법은 이것뿐이다."""
    run_dir = _write_run(tmp_path, [_row("DEV-001", trace_ids=["t1"])])

    metadata = run_metadata(load_run(run_dir))

    assert metadata["dataset_digest"] == "2d4e276eed53"
    assert metadata["prompt_variant"] == "current"
    assert metadata["linked_cases"] == 1


def test_push_writes_run_items_and_two_layers_of_scores(tmp_path: Path) -> None:
    """케이스 판정은 trace에, 회차 수치는 run에 붙는다 — 층이 다르면 화면도 다르다."""
    run_dir = _write_run(
        tmp_path,
        [_row("DEV-001", trace_ids=["t1"]), _row("DEV-002", trace_ids=["t2", "t3"], passed=False)],
    )
    client = _FakeClient()

    assert push_run(client, load_run(run_dir)) == 0

    linked = client.api.dataset_run_items.calls
    assert [(call["dataset_item_id"], call["trace_id"]) for call in linked] == [
        ("agent-quality-dev-DEV-001", "t1"),
        ("agent-quality-dev-DEV-002", "t3"),
    ]
    assert {call["run_name"] for call in linked} == {run_dir.name}

    case_scores = [score for score in client.scores if score["name"] == "case_pass"]
    assert [(score["trace_id"], score["value"]) for score in case_scores] == [("t1", 1), ("t3", 0)]
    # bool은 float의 하위형이라 그냥 넘기면 NUMERIC으로 새어 들어간다.
    assert {score["data_type"] for score in case_scores} == {"BOOLEAN"}

    # Dataset Run 화면이 안 그려지므로 화면에서 쓰는 통로는 이 셋뿐이다.
    marks = {
        (score["name"], score["trace_id"]): score["value"]
        for score in client.scores
        if score["name"] in ("eval_run", "eval_case")
    }
    assert marks[("eval_case", "t1")] == "DEV-001"
    assert marks[("eval_case", "t3")] == "DEV-002"
    assert marks[("eval_run", "t1")] == run_dir.name

    run_scores = {score["name"]: score for score in client.scores if "dataset_run_id" in score}
    assert set(run_scores) == {"intent_accuracy", "case_pass_rate", "error_count"}
    assert all(score["data_type"] == "NUMERIC" for score in run_scores.values())


def test_latency_is_not_a_run_score() -> None:
    """지연은 로컬 실행 환경에 좌우된다. 회차 곡선에 올리면 프롬프트 탓으로 오인한다."""
    assert not [name for name in RUN_SCORES if "latency" in name]


def test_scores_do_not_go_through_the_otel_gated_helper() -> None:
    """`client.create_score()`는 `tracing_enabled=False`면 조용히 return 한다.

    이 스크립트의 클라이언트는 span을 안 내보내려고 그렇게 만들어진다. 그래서 그
    헬퍼를 쓰면 Score가 **오류 없이 사라진다** — 2026-08-26 첫 Run에서 41건이 실제로
    그렇게 날아갔고, 가짜 클라이언트가 `create_score`를 받아주는 바람에 테스트는
    통과했다. 동기 REST 경로(`api.scores.create`)를 쓰는지 원문으로 잠근다.
    """
    source = Path(push_langfuse_dataset_run.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]  # 모듈 docstring의 설명 문장은 제외한다

    assert "client.api.scores.create(" in body
    assert "client.create_score(" not in body


def test_rerunning_the_same_push_does_not_pile_up_scores(tmp_path: Path) -> None:
    """id를 안 주면 서버가 매번 새로 발급해 같은 trace에 case_pass가 여러 개 붙는다.

    그러면 화면에서 어느 값이 최신인지 알 수 없다. 같은 (회차, trace, 이름)이면
    같은 id가 나와야 재실행이 덮어쓴다.
    """
    run_dir = _write_run(tmp_path, [_row("DEV-001", trace_ids=["t1"])])

    first, second = _FakeClient(), _FakeClient()
    push_run(first, load_run(run_dir))
    push_run(second, load_run(run_dir))

    assert [score["id"] for score in first.scores] == [score["id"] for score in second.scores]
    assert len({score["id"] for score in first.scores}) == len(first.scores)


def test_score_marks_carry_our_own_identifiers_not_user_text() -> None:
    """Score는 마스킹을 타지 않는다 — 자유 텍스트를 실으면 발화가 그대로 나간다.

    CATEGORICAL을 쓰는 자리는 **우리가 지은 식별자**(회차 폴더명·case_id)로 좁힌다.
    발화·응답을 싣는 경로가 생기면 이 테스트가 먼저 깨져야 한다.
    """
    source = Path(push_langfuse_dataset_run.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]

    categorical_values = re.findall(r'\("(\w+)", ([\w.]+), "CATEGORICAL"\)', body)
    assert categorical_values == [
        ("eval_run", "payload.run_id"),
        ("eval_case", "link.case_id"),
    ]
