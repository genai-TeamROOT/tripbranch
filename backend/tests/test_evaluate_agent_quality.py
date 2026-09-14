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
    assert len(load_cases("dev")) == 64
    assert len(load_cases("final")) == 15


def test_dev_goldset_keeps_five_turns_per_intent() -> None:
    """인텐트마다 턴 5건이 바닥이다.

    `macro_f1`은 **인텐트별 F1의 평균**이라(`build_summary`) 어떤 인텐트의 턴이
    1건이면 그 한 건이 뒤집힐 때 해당 클래스 F1이 1.0에서 0으로 떨어지고 Macro F1이
    1/7만큼 움직인다. 그 상태로 모델을 견주면 모델 차이가 아니라 동전 던지기를 잰다.

    위 건수 단언과 달리 이것은 **골드셋이 커져도 계속 유효한 불변식**이다. 케이스를
    덜어낼 때 COMPARE·GENERAL·OUT_OF_SCOPE가 조용히 1건으로 돌아가는 것을 막는다
    (2026-09-14 보강 전 실제로 그 상태였다 — 셋 다 1건).
    """

    counts: dict[str, int] = {}
    for case in load_cases("dev"):
        for intent in case.expected_turn_intents:
            counts[intent] = counts.get(intent, 0) + 1

    assert counts, "dev 골드셋이 비어 있다"
    thin = {intent: n for intent, n in counts.items() if n < 5}
    assert not thin, f"턴이 5건 미만인 인텐트가 있다: {thin}"


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
            "prompt_variant": "router-context@legacy-1.0.0",
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
    assert "router-context@legacy-1.0.0" in report
