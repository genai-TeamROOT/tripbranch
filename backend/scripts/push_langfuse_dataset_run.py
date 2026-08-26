"""평가 1회차를 Langfuse Dataset Run으로 올린다.

배경: `sync_langfuse_dataset`이 골드셋 **케이스**를 Langfuse에 올려놨지만, 그 케이스가
      **어느 실행에서 어떤 trace로 돌았는지**는 아직 이어지지 않는다. 그래서 화면에서
      "DEV-014가 지난주엔 통과했는데 이번엔 왜 깨졌나"를 못 짚는다 —
      `case_results.csv`를 열고 trace를 손으로 찾아야 한다. Dataset Run이 그 연결이다.

      **CSV가 정본이다.** 이 스크립트는 이미 끝난 실행 폴더를 읽어 올리기만 한다.
      평가 자체(`evaluate_agent_quality`)는 Langfuse를 부르지 않는다 — 관측이 죽어도
      평가는 돌아야 하고, 올리기가 실패해도 실행 결과는 디스크에 남아야 한다.

방법: 실행 폴더 하나(`test_results/agent_quality/runs/<run_id>/`)를 읽는다.

  --check (기본) 읽기만. 무엇이 어디에 연결될지 보여준다.
  --push         Langfuse에 쓴다. `--yes` 없이는 계획만 보여주고 멈춘다.
  --run <경로>   대상 실행 폴더. 생략하면 가장 최근 폴더(`--latest`와 같다).

  **케이스 하나에 trace 하나만 붙는다.** 한 케이스가 턴 N개(=trace N개)로 돌지만,
  같은 (run, item)에 run item을 두 번 만들면 **덮어쓴다**(2026-08-26 실측 — 두 번
  create 하면 id는 둘 다 돌아오는데 목록에는 나중 것 하나만 남는다). 그래서
  **마지막 턴의 trace**를 대표로 걸고, 턴별 trace id는 전부 metadata에 남긴다.
  마지막 턴을 고르는 이유는 `expected_final_conditions`가 그 턴의 결과이기 때문이다.

  **Score를 두 층으로 남긴다.** 케이스 단위(`case_pass`)는 trace에, 회차 단위
  (`intent_accuracy` 등)는 run에 붙인다. 둘 다 수치·불리언만 올린다 — Score는 마스킹을
  타지 않아서 자유 텍스트를 실으면 `capture_content=false` 환경에서도 발화가 샌다
  (`observability/langfuse_tracing.record_score` docstring과 같은 판단).

  **`client.create_score()`를 쓰지 않는다.** 그건 OTel 파이프라인을 타는데 첫머리에
  `if not self._tracing_enabled: return`이 있다(SDK 4.14.5). 배치 스크립트의 클라이언트는
  span을 안 내보내려고 `tracing_enabled=False`로 만들기 때문에, 그 헬퍼를 쓰면 Score가
  **오류 없이 조용히 사라진다**(2026-08-26 첫 Run에서 41건이 그렇게 날아갔다).
  `api.scores.create()`는 동기 REST 호출이라 그 게이트도, flush 대기도 없다.

판정 기준 — 합격/불합격:
  * trace id가 하나도 없는 실행은 불합격이다. 관측이 꺼진 채로 돌린 것이라 연결할 게
    없다 — 빈 Run을 만들면 "돌렸는데 결과가 없는 회차"로 남아 집계를 더럽힌다.
  * 골드셋 해시(`dataset_digest`)를 Run metadata에 남긴다. Dataset이 다른 골드셋이면
    회차 비교가 거짓이 되므로, 올리기 전에 `sync_langfuse_dataset --check`를 먼저 본다.

실행: cd backend && .venv/bin/python -m scripts.push_langfuse_dataset_run
      cd backend && .venv/bin/python -m scripts.push_langfuse_dataset_run --push --yes

주의: Run은 지우는 기능을 두지 않았다. 회차 기록이 사라지면 그 수치로 내린 판단을
      되짚을 수 없다. 잘못 올렸으면 Langfuse UI에서 지운다.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from scripts.sync_langfuse_dataset import DATASET_NAMES, _client, item_id

RUNS_DIR: Final = Path(__file__).resolve().parents[1] / "test_results" / "agent_quality" / "runs"

# 회차 단위로 올릴 값. `summary.json`에 있는 것 중 **추세가 의미 있는 수치**만 고른다.
# 지연(p50/p95)은 여기 안 넣는다 — 로컬 실행 환경에 좌우돼서 회차 비교로 읽으면
# 프롬프트 변경 탓으로 오인한다.
RUN_SCORES: Final[tuple[str, ...]] = (
    "intent_accuracy",
    "case_pass_rate",
    "multi_turn_case_pass_rate",
    "condition_field_accuracy",
    "condition_exact_match_rate",
    "error_count",
)


@dataclass(frozen=True)
class CaseLink:
    """케이스 하나를 trace 하나에 잇는 계획."""

    case_id: str
    dataset_item_id: str
    trace_id: str
    turn_trace_ids: tuple[str, ...]
    case_pass: bool
    error: str

    @property
    def turn_count(self) -> int:
        return len(self.turn_trace_ids)


@dataclass(frozen=True)
class RunPayload:
    run_id: str
    split: str
    created_at: str
    dataset_digest: str
    prompt_variant: str
    summary: dict[str, Any]
    links: list[CaseLink] = field(default_factory=list)
    # trace id가 없어 못 잇는 케이스. 관측이 꺼진 채로 돈 실행에서 생긴다.
    skipped: list[str] = field(default_factory=list)

    @property
    def dataset_name(self) -> str:
        return DATASET_NAMES[self.split]


def latest_run_dir() -> Path:
    if not RUNS_DIR.exists():
        raise FileNotFoundError(f"실행 폴더가 없다: {RUNS_DIR}")
    candidates = sorted(path for path in RUNS_DIR.iterdir() if path.is_dir())
    if not candidates:
        raise FileNotFoundError(f"실행 폴더가 비어 있다: {RUNS_DIR}")
    return candidates[-1]


def _truthy(value: str) -> bool:
    return value.strip().lower() == "true"


def load_run(run_dir: Path) -> RunPayload:
    """실행 폴더에서 요약과 케이스별 trace 연결을 읽는다.

    `summary.json`과 `case_results.csv`를 함께 본다 — split은 요약에만 있고,
    trace id는 케이스 표에만 있다.
    """

    summary_path = run_dir / "summary.json"
    results_path = run_dir / "case_results.csv"
    for path in (summary_path, results_path):
        if not path.exists():
            raise FileNotFoundError(f"{path.name}이 없다: {path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    split = summary.get("split")
    if split not in DATASET_NAMES:
        raise ValueError(f"모르는 split이다: {split!r} (아는 값: {sorted(DATASET_NAMES)})")

    links: list[CaseLink] = []
    skipped: list[str] = []
    with results_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"케이스가 하나도 없다: {results_path}")
    if "langfuse_trace_ids" not in rows[0]:
        raise ValueError(
            f"{results_path.name}에 langfuse_trace_ids 열이 없다 — "
            "trace id를 남기기 전에 돌린 실행이라 연결할 수 없다."
        )

    for row in rows:
        case_id = row["case_id"]
        trace_ids = tuple(json.loads(row["langfuse_trace_ids"] or "[]"))
        if not trace_ids:
            skipped.append(case_id)
            continue
        links.append(
            CaseLink(
                case_id=case_id,
                dataset_item_id=item_id(case_id, split),
                # 마지막 턴이 대표다 — expected_final_conditions가 그 턴의 결과다.
                trace_id=trace_ids[-1],
                turn_trace_ids=trace_ids,
                case_pass=_truthy(row.get("case_pass", "")),
                error=row.get("error", ""),
            )
        )

    return RunPayload(
        run_id=summary.get("run_id") or run_dir.name,
        split=split,
        created_at=str(summary.get("created_at", "")),
        dataset_digest=str(summary.get("dataset_digest", "")),
        prompt_variant=str(summary.get("prompt_variant", "")),
        summary=summary,
        links=links,
        skipped=skipped,
    )


def run_metadata(payload: RunPayload) -> dict[str, Any]:
    """Run에 남길 재현 정보.

    **골드셋 해시를 반드시 남긴다.** Dataset이 다른 골드셋으로 갱신된 뒤 이 회차를
    보면, 무엇으로 잰 수치인지 알 수 있는 건 이 값뿐이다.
    """

    return {
        "run_id": payload.run_id,
        "split": payload.split,
        "created_at": payload.created_at,
        "dataset_digest": payload.dataset_digest,
        "prompt_variant": payload.prompt_variant,
        "linked_cases": len(payload.links),
        "skipped_cases": len(payload.skipped),
    }


def _print_plan(payload: RunPayload) -> None:
    print(f"\n=== {payload.run_id} ===")
    print(f"  Dataset : {payload.dataset_name} (split={payload.split})")
    print(f"  골드셋 해시: {payload.dataset_digest}")
    print(f"  연결 대상 : {len(payload.links)}건")
    multi = [link for link in payload.links if link.turn_count > 1]
    print(f"    - 1턴 {len(payload.links) - len(multi)}건 · 다중 턴 {len(multi)}건")
    failed = [link for link in payload.links if not link.case_pass]
    print(f"    - 통과 {len(payload.links) - len(failed)}건 · 실패 {len(failed)}건")
    if payload.skipped:
        print(f"  ✗ trace 없음 {len(payload.skipped)}건: {', '.join(payload.skipped[:5])}...")
    print("  회차 Score:")
    for name in RUN_SCORES:
        value = payload.summary.get(name)
        if isinstance(value, (int, float)):
            print(f"    - {name}: {value}")


def push_run(client: Any, payload: RunPayload) -> int:
    """Run item과 Score를 올린다. 이미 있는 run 이름이면 그 위에 갱신된다."""

    metadata = run_metadata(payload)
    description = (
        f"{payload.split} 골드셋 {len(payload.links)}건 · "
        f"digest={payload.dataset_digest} · variant={payload.prompt_variant}"
    )
    for link in payload.links:
        client.api.dataset_run_items.create(
            run_name=payload.run_id,
            dataset_item_id=link.dataset_item_id,
            trace_id=link.trace_id,
            run_description=description,
            metadata=metadata,
        )
        # 케이스 단위 판정은 trace에 붙인다 — 화면에서 그 trace를 열면 바로 보인다.
        client.api.scores.create(
            name="case_pass",
            value=int(link.case_pass),
            data_type="BOOLEAN",
            trace_id=link.trace_id,
        )
    print(f"✓ run item {len(payload.links)}건 · case_pass Score {len(payload.links)}건")

    dataset_run = client.api.datasets.get_run(
        dataset_name=payload.dataset_name, run_name=payload.run_id
    )
    written = 0
    for name in RUN_SCORES:
        value = payload.summary.get(name)
        if not isinstance(value, (int, float)):
            continue
        client.api.scores.create(
            name=name,
            value=float(value),
            data_type="NUMERIC",
            dataset_run_id=dataset_run.id,
        )
        written += 1
    print(f"✓ 회차 Score {written}건 → run={payload.run_id}")
    return 0


def run_check(run_dir: Path) -> int:
    payload = load_run(run_dir)
    _print_plan(payload)
    if not payload.links:
        print("\n✗ 연결할 trace가 하나도 없다 — 관측을 켜고 다시 돌려야 한다.")
        return 1
    print("\n(--push --yes 로 올린다)")
    return 0


def run_push(run_dir: Path, *, confirmed: bool) -> int:
    payload = load_run(run_dir)
    _print_plan(payload)
    if not payload.links:
        print("\n✗ 연결할 trace가 하나도 없다 — 관측을 켜고 다시 돌려야 한다.")
        return 1
    if not confirmed:
        print("\n확인용 실행이다. 실제로 올리려면 --yes 를 붙인다.")
        return 0

    client = _client()
    if client is None:
        return 1
    return push_run(client, payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, default=None, help="실행 폴더(생략하면 최신)")
    parser.add_argument("--push", action="store_true", help="Langfuse에 올린다")
    parser.add_argument("--yes", action="store_true", help="--push의 실제 실행을 확인한다")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    # 실행 폴더가 낡았거나(열이 없음) 계약이 안 맞는 건 예상 가능한 실패다.
    # 트레이스백을 던지면 무엇을 고쳐야 하는지가 오히려 안 보인다.
    try:
        run_dir = args.run or latest_run_dir()
        if args.push:
            return run_push(run_dir, confirmed=args.yes)
        return run_check(run_dir)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"✗ {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
