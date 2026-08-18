"""Intent 분류의 thinking 예산별 정확도·지연을 실제 Gemini로 측정한다.

역할: `intent_classification_cases_*.csv`의 케이스를 RealGeminiProvider의
classify_intent()에 직접 넣고, `thinking_budget`만 바꿔가며 판정과 지연을 잰다.
프롬프트·응답 스키마·temperature는 그대로 두고 예산 하나만 변수로 삼는다.

**scripts/test_intent_classification.py와 재는 대상이 다르다.** 그쪽은
로컬 서버의 `/api/interpret`을 때려 라우트→오케스트레이터→Provider 전 구간과
2단계 조건 추출값까지 확인하는 엔드투엔드 도구다. 이 스크립트는 서버 없이
Provider의 1단계 분류만 떼어 재는 대신, 케이스를 CSV에서 읽고 thinking 예산을
바꿀 수 있다. 예산 비교가 목적이면 이쪽, 전 구간 회귀 확인이 목적이면 그쪽을 쓴다.

폴백 모델은 쓰지 않는다 — thinking 특성이 다른 별개 모델이라 섞이면 예산 비교가
무의미해진다(2026-08-10에 실제로 폴백 모델 응답이 결과를 오염시킨 적이 있다).

입력: `--cases`로 지정한 CSV
      (기본 test_results/intent_cot_2026-08-11/intent_classification_cases_2026-08-11.csv).
      `.env`에 LLM_API_KEY 필요. 서버는 띄우지 않아도 된다.
출력: 표준 출력 + `<--out-dir>/measure_intent_thinking_<tag>.json`
      (기본 test_results/intent_cot_2026-08-11/. 다른 실험은 `--out-dir`로 폴더를 나눈다)
호출 시점: `python -m scripts.measure_intent_thinking --budget 0`처럼 수동 실행한다
(1회성 측정 도구, pytest 스위트에는 포함하지 않는다 — 실제 API 호출 비용 때문).

재측정이 필요한 시점: 프롬프트 규칙을 추가·수정했을 때, thinking 예산을 코드에
적용한 뒤 실제 경로가 측정값을 재현하는지 확인할 때, 모델을 교체할 때.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from google.genai import types as genai_types

from app.config import settings
from app.providers.gemini import RealGeminiProvider

RESULTS_DIR = Path(__file__).resolve().parent.parent / "test_results"
EXPERIMENT_DIR = RESULTS_DIR / "intent_cot_2026-08-11"
DEFAULT_CASES = EXPERIMENT_DIR / "intent_classification_cases_2026-08-11.csv"
DEFAULT_MODEL = "gemini-2.5-flash"

# thinking_budget을 실을 자리가 RealGeminiProvider 안쪽(_try_model)이라, 프로덕션
# 코드를 고치지 않고 재려면 SDK config 생성만 감싸는 수밖에 없다.
#
# 코드가 classify_intent에 예산을 싣게 된 뒤에도 이 우회는 남는다 — `--budget`은
# kwargs를 덮어쓰므로 코드가 정한 값 대신 측정하려는 값이 실린다. 코드에 박힌 값과
# 다른 예산을 재는 것이 이 스크립트의 존재 이유라 그대로 둔다.
#
# 반대로 `--budget`을 생략하면 덮어쓰지 않으므로 **코드가 정한 값이 그대로 나간다.**
# 즉 생략은 "모델 기본값"이 아니다 — 모델 기본값 자체를 재려면 코드에서 그 호출의
# 예산 지정을 빼고 돌려야 한다.
_ORIGINAL_CONFIG = genai_types.GenerateContentConfig
_budget: int | None = None


def _config_with_budget(**kwargs: object) -> genai_types.GenerateContentConfig:
    if _budget is not None:
        kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_budget=_budget)
    return _ORIGINAL_CONFIG(**kwargs)


@dataclass
class CaseResult:
    number: str
    utterance: str
    group: str
    expected: str
    predictions: list[str | None] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def hits(self) -> int:
        return sum(1 for p in self.predictions if p == self.expected)

    @property
    def mean_latency_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0


def load_cases(path: Path, only: str) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))
    if only:
        wanted = {n.strip() for n in only.split(",")}
        rows = [r for r in rows if r["번호"] in wanted]
    return rows


async def classify_once(
    provider: RealGeminiProvider, case: dict[str, str]
) -> tuple[str | None, str | None, float]:
    started = time.perf_counter()
    try:
        result = (
            await provider.classify_intent(
                case["입력문장"],
                has_previous_recommendation=case["has_previous_recommendation"] == "True",
                shown_place_count=int(case["shown_place_count"]),
                pending_clarification=case["pending_clarification"] or None,
                last_intent=case["last_intent"] or None,
            )
        ).data
        return result.intent.value, None, (time.perf_counter() - started) * 1000
    except Exception as exc:  # noqa: BLE001 — 한 건이 실패해도 측정을 계속한다
        detail = getattr(exc, "details", None) or str(exc)
        return None, f"{type(exc).__name__}: {detail}", (time.perf_counter() - started) * 1000


async def run(cases: list[dict[str, str]], args: argparse.Namespace) -> list[CaseResult]:
    provider = RealGeminiProvider(api_key=settings.llm_api_key, model_names=[args.model])
    results: list[CaseResult] = []
    total = len(cases) * args.repeat
    done = 0

    for case in cases:
        result = CaseResult(
            number=case["번호"], utterance=case["입력문장"],
            group=case["그룹"], expected=case["기대_intent"],
        )
        for _ in range(args.repeat):
            done += 1
            predicted, error, latency = await classify_once(provider, case)
            result.predictions.append(predicted)
            result.latencies_ms.append(latency)
            if error:
                result.errors.append(error)
            await asyncio.sleep(args.delay)

        mark = "O" if result.hits == args.repeat else ("X" if result.hits == 0 else "~")
        shown = (
            result.predictions[0]
            if args.repeat == 1
            else f"{result.predictions} ({result.hits}/{args.repeat})"
        )
        print(
            f"[{done:3d}/{total}] {mark} {result.number:>3s} {result.utterance[:26]:28s} "
            f"기대={result.expected:12s} 실제={shown}  {result.mean_latency_ms:.0f}ms",
            flush=True,
        )
        results.append(result)
    return results


def report(results: list[CaseResult], args: argparse.Namespace) -> dict[str, object]:
    passed = [r for r in results if r.hits == args.repeat]
    partial = [r for r in results if 0 < r.hits < args.repeat]
    failed = [r for r in results if r.hits == 0]
    errored = [r for r in results if r.errors]
    latencies = sorted(r.mean_latency_ms for r in results)
    budget_label = "미설정" if _budget is None else str(_budget)

    print("\n" + "=" * 74)
    print(f"모델={args.model}  thinking={budget_label}  반복={args.repeat}")
    print(f"전체 정답: {len(passed)}/{len(results)} = {len(passed) / len(results) * 100:.1f}%")
    if partial:
        print(f"부분 정답(흔들림): {len(partial)}건")
    print("-" * 74)

    by_group: dict[str, list[CaseResult]] = {}
    for r in results:
        by_group.setdefault(r.group, []).append(r)
    for group, group_results in sorted(by_group.items()):
        hit = sum(1 for r in group_results if r.hits == args.repeat)
        print(f"  {group:12s} {hit}/{len(group_results)}")

    if failed or partial:
        print("-" * 74)
        print("불일치:")
        for r in failed + partial:
            print(f"  {r.number:>3s} \"{r.utterance}\"")
            print(f"       기대={r.expected} → 실제={r.predictions}")
    if errored:
        print("-" * 74)
        print(f"호출 오류 {len(errored)}건:")
        for r in errored:
            print(f"  {r.number:>3s} {r.errors[0][:90]}")
    print("-" * 74)
    print(
        f"지연 중앙값 {statistics.median(latencies):.0f}ms  "
        f"p90 {latencies[int(len(latencies) * 0.9)]:.0f}ms  최대 {latencies[-1]:.0f}ms"
    )
    print("=" * 74)

    return {
        "model": args.model,
        "thinking_budget": budget_label,
        "repeat": args.repeat,
        "correct": len(passed),
        "total": len(results),
        "cases": [
            {
                "번호": r.number, "입력문장": r.utterance, "그룹": r.group,
                "기대_intent": r.expected, "예측": r.predictions,
                "정답수": r.hits, "평균지연ms": round(r.mean_latency_ms),
                "오류": r.errors,
            }
            for r in results
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=None,
                        help="thinking_budget. 0=끔, 생략하면 모델 기본값(동적)")
    parser.add_argument("--repeat", type=int, default=1, help="케이스당 반복 횟수")
    parser.add_argument("--delay", type=float, default=1.0, help="호출 간 대기(초)")
    parser.add_argument("--only", default="", help="특정 번호만 (쉼표 구분)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--tag", default="", help="결과 파일 이름 접미사")
    parser.add_argument("--out-dir", type=Path, default=EXPERIMENT_DIR,
                        help="결과 JSON을 저장할 폴더. 실험마다 폴더를 나눠 쓴다")
    args = parser.parse_args()

    if not settings.llm_api_key:
        raise SystemExit("LLM_API_KEY가 없습니다. backend/.env를 확인하세요.")
    if not args.cases.exists():
        raise SystemExit(f"케이스 파일이 없습니다: {args.cases}")
    # 결과는 전 케이스 호출이 끝난 뒤에 쓰므로, 저장 실패는 측정 비용을 통째로 날린다.
    # 실제 API를 때리기 전에 폴더부터 확보한다.
    args.out_dir.mkdir(parents=True, exist_ok=True)

    global _budget
    if args.budget is not None:
        _budget = args.budget
        # RealGeminiProvider가 참조하는 이름을 바꿔야 _try_model()에 반영된다.
        import app.providers.gemini as gemini_module

        gemini_module.genai_types.GenerateContentConfig = _config_with_budget

    cases = load_cases(args.cases, args.only)
    if not cases:
        raise SystemExit("측정할 케이스가 없습니다.")

    results = asyncio.run(run(cases, args))
    payload = report(results, args)

    tag = args.tag or ("budget" + str(args.budget) if args.budget is not None else "default")
    out = args.out_dir / f"measure_intent_thinking_{tag}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과 저장: {out}")


if __name__ == "__main__":
    main()
