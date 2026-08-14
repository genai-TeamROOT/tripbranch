"""scripts.evaluate_agent_quality의 외부 API 없는 지표 계산 회귀 테스트."""

from __future__ import annotations

from scripts.evaluate_agent_quality import (
    CaseResult,
    EvaluationCase,
    build_summary,
    dataset_digest,
    load_cases,
    write_markdown_report,
)


def _case(case_id: str, expected_intent: str = "RECOMMEND") -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        title=case_id,
        turns=("테스트 입력",),
        expected_turn_intents=(expected_intent,),
        expected_final_conditions={"search_center": "경복궁"},
        device_location=None,
        note="",
    )


def _result(
    case: EvaluationCase,
    *,
    actual_intent: str,
    condition_matches: dict[str, bool],
) -> CaseResult:
    return CaseResult(
        case=case,
        actual_turn_intents=(actual_intent,),
        actual_final_conditions={"search_center": "경복궁"},
        intent_matches=(actual_intent == case.expected_turn_intents[0],),
        condition_matches=condition_matches,
        client_elapsed_ms=100.0,
        server_elapsed_ms=50.0,
    )


def test_example_goldsets_have_requested_split_counts() -> None:
    assert len(load_cases("dev")) == 35
    assert len(load_cases("final")) == 15


def test_dataset_digest_is_stable_for_same_goldset() -> None:
    cases = load_cases("dev")
    assert dataset_digest(cases) == dataset_digest(cases)


def test_summary_calculates_macro_f1_and_condition_accuracy() -> None:
    recommend = _case("A", "RECOMMEND")
    info = _case("B", "INFO")
    results = [
        _result(recommend, actual_intent="RECOMMEND", condition_matches={"search_center": True}),
        _result(info, actual_intent="RECOMMEND", condition_matches={"search_center": False}),
    ]

    summary, per_intent = build_summary(results)

    assert summary["intent_accuracy"] == 0.5
    assert summary["condition_field_accuracy"] == 0.5
    assert summary["condition_exact_match_rate"] == 0.5
    assert summary["macro_f1"] == 1 / 3
    assert {row["intent"] for row in per_intent} == {"INFO", "RECOMMEND"}


def test_markdown_report_explains_metrics_and_mismatch(tmp_path) -> None:
    case = _case("A")
    result = _result(case, actual_intent="INFO", condition_matches={"search_center": False})
    summary, per_intent = build_summary([result])
    summary.update(
        {
            "run_id": "2026-08-14_1200_dev_1case_example",
            "created_at": "2026-08-14T12:00:00+09:00",
            "split": "dev",
            "dataset_digest": "example",
        }
    )

    write_markdown_report(
        run_dir=tmp_path,
        results=[result],
        summary=summary,
        per_intent=per_intent,
        labels=["INFO", "RECOMMEND"],
        matrix_rows=[
            {"expected": "RECOMMEND", "INFO": 1, "RECOMMEND": 0},
            {"expected": "INFO", "INFO": 0, "RECOMMEND": 0},
        ],
    )

    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "## 혼동행렬" in report
    assert "## 불일치·오류 케이스" in report
    assert "조건 불일치" in report
