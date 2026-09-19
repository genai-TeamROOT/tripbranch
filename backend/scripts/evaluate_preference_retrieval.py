"""Evaluate TripBranch preference retrieval results against the closed-pool gold set.

The heavy chunking/embedding experiment runs in the reference Colab notebook. This
script validates the gold set, re-scores the notebook's ``rankings_top5.csv`` (or
its result ZIP), and records reproducible run artifacts under
``backend/test_results/preference_retrieval/runs``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = BACKEND_DIR / "test_results" / "preference_retrieval"
SPLIT_PATHS = {
    "dev": EVAL_DIR / "evaluation_dev.csv",
    "final": EVAL_DIR / "evaluation_final.csv",
}
CANDIDATES_PATH = EVAL_DIR / "candidate_places.csv"
QRELS_PATH = EVAL_DIR / "qrels.csv"
CORPUS_PATH = EVAL_DIR / "fixtures" / "evaluation_corpus.csv"
HISTORY_PATH = EVAL_DIR / "history.csv"

QUERY_COLUMNS = {
    "case_id",
    "preference_code",
    "preference_label",
    "query",
}
RANKING_COLUMNS = {"combo_id", "case_id", "content_id", "rank"}
HISTORY_COLUMNS = [
    "run_id",
    "created_at",
    "split",
    "dataset_digest",
    "experiment_label",
    "query_count",
    "candidate_count",
    "combo_count",
    "best_combo_id",
    "top_k",
    "precision_at_k",
    "strict_precision_at_k",
    "ndcg_at_k",
    "build_seconds",
    "mean_search_ms",
    "p95_search_ms",
    "results_source",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TripBranch 취향 RAG 검색 골드셋 평가")
    parser.add_argument("--split", choices=("dev", "final"), default="dev")
    parser.add_argument(
        "--results",
        type=Path,
        help="Colab 결과 ZIP, 결과 폴더 또는 rankings_top5.csv 경로",
    )
    parser.add_argument("--label", default="current", help="실험 식별용 이름")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None, help="점검용 앞 N개 질의")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="골드셋 계약과 건수만 확인하고 결과를 저장하지 않음",
    )
    return parser.parse_args()


def _read_csv(path: Path, *, required: set[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = sorted((required or set()) - set(frame.columns))
    if missing:
        raise ValueError(f"{path.name}: 필수 열이 없습니다: {missing}")
    return frame


def _dataset_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def load_and_validate(
    split: str, limit: int | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    queries_path = SPLIT_PATHS[split]
    queries = _read_csv(queries_path, required=QUERY_COLUMNS)
    if queries.empty:
        raise ValueError(
            f"{queries_path.name}에는 아직 최종 질의가 없습니다. "
            "현재 16개 기존 질의는 이미 실험에 사용되어 dev로 분류했습니다."
        )
    if queries.case_id.duplicated().any():
        dupes = queries.loc[queries.case_id.duplicated(False), "case_id"].tolist()
        raise ValueError(f"질의 case_id가 중복됩니다: {dupes}")
    if limit is not None:
        queries = queries.head(limit).copy()

    candidates = _read_csv(CANDIDATES_PATH, required={"content_id", "place_title"})
    qrels = _read_csv(
        QRELS_PATH,
        required={"content_id", "preference_code", "relevance_grade_final"},
    )
    candidates["content_id"] = candidates.content_id.astype(str)
    qrels["content_id"] = qrels.content_id.astype(str)
    qrels["relevance_grade_final"] = pd.to_numeric(
        qrels.relevance_grade_final, errors="raise"
    ).astype(int)

    if candidates.content_id.duplicated().any():
        raise ValueError("candidate_places.csv에 content_id 중복이 있습니다")
    if qrels.duplicated(["content_id", "preference_code"]).any():
        raise ValueError("qrels.csv에 content_id × preference_code 중복이 있습니다")
    invalid_grades = sorted(set(qrels.relevance_grade_final) - {0, 1, 2})
    if invalid_grades:
        raise ValueError(f"qrels 관련도는 0/1/2만 허용합니다: {invalid_grades}")

    candidate_ids = set(candidates.content_id)
    if set(qrels.content_id) != candidate_ids:
        raise ValueError("qrels의 장소 집합이 candidate_places의 장소 집합과 다릅니다")

    query_preferences = set(queries.preference_code)
    missing_preferences = sorted(query_preferences - set(qrels.preference_code))
    if missing_preferences:
        raise ValueError(f"qrels에 없는 취향 코드입니다: {missing_preferences}")
    expected_count = len(candidates)
    incomplete = {
        preference: len(group)
        for preference, group in qrels[qrels.preference_code.isin(query_preferences)].groupby(
            "preference_code"
        )
        if len(group) != expected_count
    }
    if incomplete:
        raise ValueError(
            f"취향별 qrels가 후보 {expected_count}곳을 모두 덮지 못합니다: {incomplete}"
        )

    if CORPUS_PATH.exists():
        corpus_ids = set(
            pd.read_csv(CORPUS_PATH, usecols=["content_id"], dtype=str).content_id
        )
        missing_corpus = sorted(candidate_ids - corpus_ids)
        if missing_corpus:
            raise ValueError(f"평가 코퍼스가 후보 장소를 누락했습니다: {missing_corpus[:10]}")

    digest = _dataset_digest([queries_path, CANDIDATES_PATH, QRELS_PATH])
    return queries, candidates, qrels, digest


def _locate_result_files(results: Path, temp_dir: Path) -> tuple[Path, Path | None, Path | None]:
    results = results.expanduser().resolve()
    if not results.exists():
        raise FileNotFoundError(results)
    root = results
    if results.suffix.lower() == ".zip":
        with zipfile.ZipFile(results) as archive:
            archive.extractall(temp_dir)
        root = temp_dir
    if root.is_file():
        rankings_path = root
        root = root.parent
    else:
        matches = list(root.rglob("rankings_top5.csv"))
        if len(matches) != 1:
            raise ValueError(
                f"{root}에서 rankings_top5.csv 한 개를 찾아야 합니다. 발견: {len(matches)}개"
            )
        rankings_path = matches[0]

    def optional(name: str) -> Path | None:
        matches = list(root.rglob(name))
        return matches[0] if len(matches) == 1 else None

    return rankings_path, optional("build_timing.csv"), optional("search_timing.csv")


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))


def evaluate_rankings(
    rankings: pd.DataFrame,
    queries: pd.DataFrame,
    qrels: pd.DataFrame,
    top_k: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = sorted(RANKING_COLUMNS - set(rankings.columns))
    if missing:
        raise ValueError(f"rankings_top5.csv 필수 열이 없습니다: {missing}")
    rankings = rankings.copy()
    rankings["content_id"] = rankings.content_id.astype(str)
    rankings["rank"] = pd.to_numeric(rankings["rank"], errors="raise").astype(int)
    rankings = rankings[rankings.case_id.isin(queries.case_id)].copy()
    if rankings.empty:
        raise ValueError("선택한 split의 case_id와 일치하는 검색 결과가 없습니다")
    if rankings.duplicated(["combo_id", "case_id", "content_id"]).any():
        raise ValueError("같은 조합·질의 안에서 동일 장소가 중복 검색됐습니다")

    expected_cases = set(queries.case_id)
    for combo_id, group in rankings.groupby("combo_id"):
        missing_cases = sorted(expected_cases - set(group.case_id))
        if missing_cases:
            raise ValueError(f"조합 {combo_id}가 질의를 누락했습니다: {missing_cases}")

    truth = {
        preference: dict(zip(group.content_id, group.relevance_grade_final, strict=True))
        for preference, group in qrels.groupby("preference_code")
    }
    query_by_id = queries.set_index("case_id")
    rows: list[dict[str, object]] = []
    for (combo_id, case_id), group in rankings.groupby(["combo_id", "case_id"]):
        case = query_by_id.loc[case_id]
        grades_by_place = truth[case.preference_code]
        ordered = group.sort_values("rank").head(top_k)
        grades = [int(grades_by_place.get(content_id, 0)) for content_id in ordered.content_id]
        grades += [0] * (top_k - len(grades))
        ideal = sorted(grades_by_place.values(), reverse=True)[:top_k]
        ideal_dcg = _dcg(ideal)
        rows.append(
            {
                "combo_id": combo_id,
                "case_id": case_id,
                "preference_code": case.preference_code,
                "preference_label": case.preference_label,
                "query": case["query"],
                f"precision_at_{top_k}": sum(grade >= 1 for grade in grades) / top_k,
                f"strict_precision_at_{top_k}": sum(grade == 2 for grade in grades) / top_k,
                f"ndcg_at_{top_k}": _dcg(grades) / ideal_dcg if ideal_dcg else 0.0,
                "retrieved_grades": json.dumps(grades, ensure_ascii=False),
            }
        )

    by_query = pd.DataFrame(rows)
    metric_columns = [
        f"precision_at_{top_k}",
        f"strict_precision_at_{top_k}",
        f"ndcg_at_{top_k}",
    ]
    summary = by_query.groupby("combo_id", as_index=False)[metric_columns].mean()
    return by_query, summary


def _merge_timings(
    summary: pd.DataFrame,
    build_path: Path | None,
    search_path: Path | None,
) -> pd.DataFrame:
    result = summary.copy()
    if build_path:
        build = pd.read_csv(build_path)
        if {"combo_id", "build_seconds"}.issubset(build.columns):
            result = result.merge(build[["combo_id", "build_seconds"]], on="combo_id", how="left")
    if search_path:
        search = pd.read_csv(search_path)
        if {"combo_id", "search_seconds"}.issubset(search.columns):
            timing = (
                search.groupby("combo_id")
                .search_seconds.agg(["mean", lambda s: s.quantile(0.95)])
                .reset_index()
            )
            timing.columns = ["combo_id", "mean_search_seconds", "p95_search_seconds"]
            result = result.merge(timing, on="combo_id", how="left")
    return result


def _report_markdown(
    run_id: str,
    split: str,
    digest: str,
    summary: pd.DataFrame,
    top_k: int,
) -> str:
    report_frame = summary.copy()
    for column in report_frame.select_dtypes(include="number").columns:
        report_frame[column] = report_frame[column].map(lambda value: f"{value:.4f}")
    headers = report_frame.columns.tolist()
    table_lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    table_lines.extend(
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in report_frame.itertuples(index=False, name=None)
    )
    lines = [
        "# 취향 RAG 검색 평가 결과",
        "",
        f"- 실행 ID: `{run_id}`",
        f"- 평가셋: `{split}`",
        f"- 골드셋 해시: `{digest}`",
        f"- 평가 기준: Precision@{top_k}, Strict Precision@{top_k}, nDCG@{top_k}",
        "- Recall은 후보 풀이 표본이고 취향별 정답 수가 달라 핵심 지표에서 제외합니다.",
        "",
        "## 조합별 평균",
        "",
        *table_lines,
        "",
        "## 해석 순서",
        "",
        f"1. Precision@{top_k}: 상위 {top_k}곳 중 실제 관련 장소의 비율",
        f"2. nDCG@{top_k}: 2점의 강한 근거 장소가 더 위에 배치되는지",
        f"3. Strict Precision@{top_k}: 상위 {top_k}곳 중 2점 장소의 비율",
        "4. 품질 차이가 작으면 구축 시간과 평균·P95 검색 시간을 함께 비교",
        "",
        "> 이 평가는 용산·성동 55개 후보만 대상으로 한 폐쇄형 비교입니다. "
        "서울 전체의 절대 성능으로 해석하지 않습니다.",
        "",
    ]
    return "\n".join(lines)


def _append_history(row: dict[str, object]) -> None:
    current = (
        pd.read_csv(HISTORY_PATH, dtype=str, keep_default_na=False)
        if HISTORY_PATH.exists()
        else pd.DataFrame(columns=HISTORY_COLUMNS)
    )
    current = pd.concat([current, pd.DataFrame([row])], ignore_index=True)
    current = current.reindex(columns=HISTORY_COLUMNS)
    current.to_csv(HISTORY_PATH, index=False, encoding="utf-8-sig")


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise ValueError("--top-k는 1 이상이어야 합니다")
    queries, candidates, qrels, digest = load_and_validate(args.split, args.limit)
    print(
        f"[{args.split}] 질의 {len(queries)}개 · 후보 {len(candidates)}곳 · "
        f"qrels {len(qrels)}행 · digest={digest}"
    )
    if args.dry_run:
        print("골드셋 검증 통과")
        return
    if args.results is None:
        raise ValueError(
            "평가하려면 --results에 Colab 결과 ZIP·폴더·rankings_top5.csv를 지정하세요"
        )

    with tempfile.TemporaryDirectory(prefix="tripbranch-preference-eval-") as temp:
        rankings_path, build_path, search_path = _locate_result_files(args.results, Path(temp))
        rankings = _read_csv(rankings_path, required=RANKING_COLUMNS)
        metrics_by_query, summary = evaluate_rankings(rankings, queries, qrels, args.top_k)
        summary = _merge_timings(summary, build_path, search_path)

    now = datetime.now().astimezone()
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", args.label).strip("-") or "current"
    run_id = f"{now.strftime('%Y-%m-%d_%H%M')}_{args.split}_{label}_{len(queries)}queries_{digest}"
    run_dir = EVAL_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    filtered_rankings = rankings[rankings.case_id.isin(queries.case_id)].copy()
    filtered_rankings.to_csv(run_dir / "rankings.csv", index=False, encoding="utf-8-sig")
    metrics_by_query.to_csv(run_dir / "metrics_by_query.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(run_dir / "metrics_summary.csv", index=False, encoding="utf-8-sig")

    config = {
        "run_id": run_id,
        "created_at": now.isoformat(timespec="seconds"),
        "split": args.split,
        "dataset_digest": digest,
        "experiment_label": args.label,
        "top_k": args.top_k,
        "query_count": len(queries),
        "candidate_count": len(candidates),
        "results_source": str(args.results.expanduser().resolve()),
    }
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "summary.json").write_text(
        json.dumps({**config, "metrics": summary.to_dict("records")}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(
        _report_markdown(run_id, args.split, digest, summary, args.top_k), encoding="utf-8"
    )

    metric_names = [
        f"precision_at_{args.top_k}",
        f"strict_precision_at_{args.top_k}",
        f"ndcg_at_{args.top_k}",
    ]
    best = summary.sort_values(f"ndcg_at_{args.top_k}", ascending=False).iloc[0]
    history_row = {
        "run_id": run_id,
        "created_at": config["created_at"],
        "split": args.split,
        "dataset_digest": digest,
        "experiment_label": args.label,
        "query_count": len(queries),
        "candidate_count": len(candidates),
        "combo_count": summary.combo_id.nunique(),
        "best_combo_id": best["combo_id"],
        "top_k": args.top_k,
        "precision_at_k": best[metric_names[0]],
        "strict_precision_at_k": best[metric_names[1]],
        "ndcg_at_k": best[metric_names[2]],
        "build_seconds": best.get("build_seconds", float("nan")),
        "mean_search_ms": best.get("mean_search_seconds", float("nan")) * 1000,
        "p95_search_ms": best.get("p95_search_seconds", float("nan")) * 1000,
        "results_source": str(args.results.expanduser().resolve()),
    }
    _append_history(history_row)
    print(summary.to_string(index=False))
    print(f"결과: {run_dir}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, zipfile.BadZipFile) as exc:
        print(f"평가를 실행하지 못했습니다: {exc}", file=sys.stderr)
        sys.exit(1)
