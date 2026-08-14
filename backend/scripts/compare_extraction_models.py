"""2단계 조건 추출 결과가 모델에 따라 갈리는지 대조한다.

역할: 같은 발화·같은 컨텍스트를 두 모델의 추출 메서드에 넣고 `LLMOutput`이 다른
케이스만 골라낸다. **기대값으로 채점하지 않는다** — `UserConditions` 15필드의 정답
세트가 없고, 그 정의는 A 소유(프롬프트 규칙)라 임의로 만들 수 없다. 대신 `A ≠ B`는
기대값 없이 판정할 수 있다는 점을 쓴다. 인텐트 분류 실험에서 68건 중 13건만 변별력이
있었던 것과 같은 접근이다(`test_results/intent_experiments_2026-08.md` §7).

**scripts/test_intent_classification.py와 다르다.** 그쪽은 로컬 서버의 `/api/interpret`을
때려 전 구간을 보지만 채점은 intent 일치 여부뿐이고, 모델을 바꾸려면 `.env`를 고쳐
재시작해야 한다. 이 스크립트는 서버 없이 Provider의 2단계 메서드만 떼어 `--models`로
여러 모델을 한 번에 돌린다.

thinking 예산은 이 스크립트가 건드리지 않는다 — 코드가 그 호출에 지정한 값이 그대로
나간다. **측정 시점의 코드 상태에 따라 결과가 달라지므로 결과 문서에 함께 남긴다.**
(2026-08-12 측정 당시 추출 호출에는 예산 지정이 없어 모델 기본값으로 돌았다. 이후
develop `f52fa01`이 `extract_recommend_conditions`에 `thinking_budget=0`을 걸었다.)

입력: `--cases` CSV(기본 intent_cot_2026-08-11의 68건). `.env`에 LLM_API_KEY 필요.
출력: 표준 출력 + `<--out-dir>/compare_extraction_<tag>.json`
호출 시점: 모델 교체를 검토할 때 수동 실행한다(1회성 측정 도구, 실제 API 호출 비용 때문에
pytest 스위트에는 넣지 않는다).

SCHEDULE은 별도 편성 프롬프트를 쓰고 OUT_OF_SCOPE는 2단계가 없어 둘 다 건너뛴다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from datetime import date
from pathlib import Path

from app.config import settings
from app.providers.gemini import RealGeminiProvider
from app.schemas import UserConditions

RESULTS_DIR = Path(__file__).resolve().parent.parent / "test_results"
DEFAULT_CASES = RESULTS_DIR / "intent_cot_2026-08-11" / "intent_classification_cases_2026-08-11.csv"

# MODIFY 추출은 "무엇을 바꾸는가"라서 기존 조건이 있어야 성립한다. 케이스 CSV에는 그
# 값이 없으므로 모든 MODIFY 케이스에 같은 기준 조건을 준다 — 두 모델이 동일한 입력을
# 받는 것만 보장하면 대조 목적에는 충분하다.
BASELINE_CONDITIONS = UserConditions(search_center="경복궁")

# 날짜 의존 추출(INFO의 visit_time)이 실행 시각에 따라 흔들리지 않게 고정한다.
REFERENCE_DATE = date(2026, 8, 12)

SKIPPED_INTENTS = {"SCHEDULE", "OUT_OF_SCOPE"}


async def extract_one(
    provider: RealGeminiProvider, case: dict[str, str]
) -> tuple[dict | None, str | None, float]:
    """케이스의 기대 intent에 맞는 2단계 메서드를 호출하고 payload를 dict로 돌려준다."""
    intent = case["기대_intent"]
    text = case["입력문장"]
    shown = int(case["shown_place_count"])
    pending = case["pending_clarification"] or None
    started = time.perf_counter()
    try:
        if intent == "RECOMMEND":
            result = await provider.extract_recommend_conditions(text)
        elif intent == "MODIFY":
            result = await provider.extract_modify_conditions(
                text,
                BASELINE_CONDITIONS,
                pending_clarification=pending,
                shown_place_count=shown,
            )
        elif intent == "INFO":
            result = await provider.extract_info_query(
                text,
                has_previous_recommendation=case["has_previous_recommendation"] == "True",
                reference_date=REFERENCE_DATE,
            )
        elif intent == "COMPARE":
            result = await provider.extract_compare_request(text, shown_place_count=shown)
        elif intent == "GENERAL":
            result = await provider.extract_general_request(text)
        else:
            raise ValueError(f"처리 대상이 아닌 intent: {intent}")
        payload = result.data.model_dump(mode="json", exclude_none=True)
        return payload, None, (time.perf_counter() - started) * 1000
    except Exception as exc:  # noqa: BLE001 — 한 건이 실패해도 대조를 계속한다
        detail = getattr(exc, "details", None) or str(exc)
        return None, f"{type(exc).__name__}: {detail}", (time.perf_counter() - started) * 1000


async def run_model(model: str, cases: list[dict[str, str]], args: argparse.Namespace) -> dict:
    provider = RealGeminiProvider(
        api_key=settings.llm_api_key, model_names=[model], timeout_seconds=args.timeout
    )
    out: dict[str, dict] = {}
    for i, case in enumerate(cases, 1):
        payload, error, latency = await extract_one(provider, case)
        out[case["번호"]] = {"payload": payload, "오류": error, "지연ms": round(latency)}
        mark = "!" if error else "."
        print(f"{mark}", end="" if i % 50 else "\n", flush=True)
        await asyncio.sleep(args.delay)
    print(flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, help="쉼표로 구분한 모델 2개 이상")
    parser.add_argument("--delay", type=float, default=1.0, help="호출 간 대기(초)")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="추출은 분류보다 길어 기본 10초로는 타임아웃이 섞인다")
    parser.add_argument("--only", default="", help="특정 번호만 (쉼표 구분)")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--tag", default="")
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    if not settings.llm_api_key:
        raise SystemExit("LLM_API_KEY가 없습니다. backend/.env를 확인하세요.")
    if not args.cases.exists():
        raise SystemExit(f"케이스 파일이 없습니다: {args.cases}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if len(models) < 2:
        raise SystemExit("--models에 모델 2개 이상이 필요합니다.")

    with args.cases.open(encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))
    if args.only:
        wanted = {n.strip() for n in args.only.split(",")}
        rows = [r for r in rows if r["번호"] in wanted]
    cases = [r for r in rows if r["기대_intent"] not in SKIPPED_INTENTS]
    skipped = len(rows) - len(cases)
    if not cases:
        raise SystemExit("대조할 케이스가 없습니다.")

    print(f"대상 {len(cases)}건 (SCHEDULE·OUT_OF_SCOPE {skipped}건 제외) × 모델 {len(models)}개\n")

    results: dict[str, dict] = {}
    for model in models:
        print(f"[{model}]")
        results[model] = asyncio.run(run_model(model, cases, args))

    base, *others = models
    by_case = {c["번호"]: c for c in cases}
    diffs: list[dict] = []
    errors: list[str] = []
    for number in by_case:
        payloads = {m: results[m][number]["payload"] for m in models}
        if any(results[m][number]["오류"] for m in models):
            errors.append(number)
            continue
        serialized = {
            m: json.dumps(p, ensure_ascii=False, sort_keys=True)
            for m, p in payloads.items()
        }
        if len({*serialized.values()}) > 1:
            diffs.append({"번호": number, "입력문장": by_case[number]["입력문장"],
                          "기대_intent": by_case[number]["기대_intent"], "payload": payloads})

    print("\n" + "=" * 74)
    print(f"대조: {' vs '.join(models)}")
    same = len(by_case) - len(diffs) - len(errors)
    print(f"동일 {same}건 / 상이 {len(diffs)}건 / 오류 {len(errors)}건")
    if diffs:
        print("-" * 74)
        for d in diffs:
            print(f"\n  {d['번호']:>3} \"{d['입력문장']}\"  ({d['기대_intent']})")
            for m in models:
                print(f"      {m:24s} {json.dumps(d['payload'][m], ensure_ascii=False)[:180]}")
    if errors:
        print("-" * 74)
        print(f"오류로 대조 못 한 케이스: {', '.join(errors)}")
    print("=" * 74)

    tag = args.tag or "extraction"
    out = args.out_dir / f"compare_extraction_{tag}.json"
    out.write_text(
        json.dumps(
            {"models": models, "reference_date": str(REFERENCE_DATE),
             "대상": len(by_case), "상이": len(diffs), "오류": errors,
             "diffs": diffs, "raw": results},
            ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"결과 저장: {out}")


if __name__ == "__main__":
    main()
