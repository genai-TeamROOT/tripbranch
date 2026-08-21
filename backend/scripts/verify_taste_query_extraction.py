"""RECOMMEND 조건 추출이 취향 발화만 taste_query에 담는지 실 LLM으로 검증한다.

프롬프트 스냅샷 테스트는 지시문 문자열만 고정할 뿐 모델이 그 지시를 따르는지는
보지 않는다. 이 스크립트는 실제로 호출해서 세 가지를 확인한다.

1. 취향 발화 -> taste_query가 채워지고, 시간·거리 조건이 섞이지 않는가
2. 비취향 발화(일정·거리·장소유형) -> taste_query가 null인가
3. "조용한/한적한" 류 발화가 concentration_intent와 taste_query를 동시에
   채우는가(co-fill) — 한 단어가 가중치 0.30(0.15+0.15)을 가져가는지 실측

2번은 실측(2026-08-19)에서 "3시간 안에 다녀올 수 있는 곳"이 취향 근거 검색에서
유사도 0.523으로 진짜 취향 발화(0.498)보다 높게 나온 것과 직결된다 — 이 문장이
taste_query에 담기면 엉뚱한 장소에 취향 점수가 붙는다.

3번은 프롬프트상 concentration_intent=AVOID 예시("조용한 공원")와 taste_query
예시("혼자 조용히 쉴 만한")가 같은 단어를 공유해서 생긴 우려다. 지금까지는
프롬프트를 읽고 한 추론이라, 실제 co-fill 비율을 측정해 배분 적절성을 판단한다.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import time

from app.config import Settings
from app.providers.gemini import RealGeminiProvider

# 2차 혼잡도 가중치(0.15)가 실제로 붙는 intent. IGNORE/null은 재순위를 안
# 켜므로(D-040) co-fill 집계에서 제외한다 — 이 둘은 "한 단어가 0.30을 먹는"
# 문제를 일으키지 않는다.
_SCORING_INTENTS = ("AVOID", "SEEK")

# (발화, taste_query가 채워져야 하는가)
CASES: tuple[tuple[str, bool], ...] = (
    # --- 취향 발화: 채워져야 한다 ---
    ("혼자 조용히 쉴 만한 곳 추천해줘", True),   # 2.1.0: "조용히" 빠지고 "쉴 만한"만
    ("부모님이랑 갈 만한 분위기 좋은 곳", True),
    ("감성적인 사진 찍기 좋은 데 알려줘", True),
    ("빈티지하고 레트로한 분위기 카페", True),
    # --- 비취향: null이어야 한다 ---
    ("3시간 안에 다녀올 수 있는 곳", False),
    ("지하철역에서 가까운 곳", False),
    ("반나절 코스로 짜줘", False),
    ("종로 맛집 추천", False),
    ("걸어서 20분 이내로", False),
    ("경복궁 근처 추천해줘", False),
    # --- 혼잡도만 → null (2.1.0: 혼잡도 단어는 concentration_intent가 받는다) ---
    ("사람 많은 곳 말고 한적한 데로", False),
    ("3시간 안에 갈 수 있는 조용한 카페", False),
    # 시끌벅적(SEEK) 제거 후 잔여("친구들이랑 놀 만한")는 밋밋해 null이 맞다.
    ("친구들이랑 시끌벅적하게 놀 만한 곳", False),
    # --- 혼합: 취향만 뽑고 혼잡도·시간·거리는 뺀다 ---
    ("지하철역 가까우면서 분위기 좋은 곳", True),
)

# 겹침 유발 발화 — 두 축 예시가 공유하는 "조용한/한적한" 단어로 만든 문장.
# 기대값을 두지 않는다(측정이 목적). 두 필드가 동시에 채워지는 비율(co-fill)이
# 이 스크립트의 핵심 산출물이다.
OVERLAP_CASES: tuple[str, ...] = (
    "조용한 데 가고 싶어",
    "한적한 곳 추천해줘",
    "사람 없는 조용한 카페",
    "붐비지 않는 데서 쉬고 싶어",
    "북적이지 않는 분위기 좋은 곳",
    "한적하고 감성적인 곳",
)

# 대조군 — 한 축만 나와야 한다. axis: 채워져야 하는 쪽("concentration" | "taste").
# 반대 축이 같이 채워지면 그게 바로 경계 오염이다.
CONTROL_CASES: tuple[tuple[str, str], ...] = (
    ("붐비는 델 피하고 싶어", "concentration"),        # AVOID지만 취향 아님
    ("사람 많고 활기찬 데 가고 싶어", "concentration"),  # SEEK
    ("빈티지하고 레트로한 카페", "taste"),               # 취향이지만 혼잡도 아님
)

# taste_query에 섞이면 안 되는 표현. 다른 필드가 이미 받는 조건들이다.
# 부분 문자열로 찾으면 "분위기"의 "분"을 시간 조건으로 오탐하므로 패턴으로 잡는다.
_LEAK_PATTERNS = (
    r"\d+\s*(시간|분|km|킬로|미터|m)\b",   # 3시간, 20분, 2km
    r"반나절|코스|일정",                      # 일정 조건
    r"지하철|역에서|도보로|걸어서",             # 교통·거리 조건
    r"\d+\s*(명|인)",                      # 인원
)

# 2.1.0 핵심 지표: 혼잡도 표현이 taste_query에 그대로 메아리치는가.
# concentration_intent가 받아야 할 단어라, taste_query에 남으면 한 선호가
# 두 축에서 0.30을 가져간다. 이 누출이 0으로 떨어지는 게 수정의 성공 기준이다.
_CROWD_PATTERNS = (
    r"조용",
    r"한적",
    r"붐비",
    r"북적",
    r"시끌",
    r"사람\s*(많|없|적)",
)


async def _extract(
    provider: RealGeminiProvider, text: str
) -> tuple[str | None, str | None, str | None, int]:
    """(taste_query, concentration_intent, 오류, ms)를 반환한다."""
    started = time.perf_counter()
    try:
        result = await provider.extract_recommend_conditions(text)
        recommend = result.data.recommend
        conditions = recommend.conditions if recommend else None
        taste = conditions.taste_query if conditions else None
        conc = conditions.concentration_intent if conditions else None
        conc_str = conc.value if conc is not None else None
        error = None
    except Exception as exc:  # noqa: BLE001 - 실 API 검증 스크립트
        taste, conc_str, error = None, None, f"{type(exc).__name__}: {exc}"
    ms = round((time.perf_counter() - started) * 1000)
    return taste, conc_str, error, ms


async def run(
    model: str | None, delay: float
) -> dict[str, list[dict[str, object]]]:
    settings = Settings()
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY가 필요합니다.")

    fast = [model] if model else settings.resolved_llm_fast_models
    provider = RealGeminiProvider(
        api_key=settings.llm_api_key,
        fast_model_names=fast,
        generation_model_names=settings.resolved_llm_generation_models,
        timeout_seconds=60.0,
    )
    print(f"판단 모델: {fast[0]}")

    taste_rows: list[dict[str, object]] = []
    for text, should_fill in CASES:
        taste, conc, error, ms = await _extract(provider, text)
        filled = bool(taste)
        leaked = [p for p in _LEAK_PATTERNS if re.search(p, taste)] if taste else []
        crowd = [p for p in _CROWD_PATTERNS if re.search(p, taste)] if taste else []
        taste_rows.append(
            {
                "발화": text,
                "기대": "채움" if should_fill else "null",
                "taste": taste if taste else "null",
                "혼잡도": conc if conc else "null",
                "일치": error is None and filled == should_fill,
                "누출": leaked,
                "혼잡누출": crowd,
                "오류": error,
                "ms": ms,
            }
        )
        print("." if error is None else "!", end="", flush=True)
        await asyncio.sleep(delay)

    overlap_rows: list[dict[str, object]] = []
    for text in OVERLAP_CASES:
        taste, conc, error, ms = await _extract(provider, text)
        crowd = [p for p in _CROWD_PATTERNS if re.search(p, taste)] if taste else []
        overlap_rows.append(
            {
                "발화": text,
                "taste": taste if taste else "null",
                "혼잡도": conc if conc else "null",
                "동시": bool(taste) and conc in _SCORING_INTENTS,
                "혼잡누출": crowd,
                "오류": error,
                "ms": ms,
            }
        )
        print("." if error is None else "!", end="", flush=True)
        await asyncio.sleep(delay)

    control_rows: list[dict[str, object]] = []
    for text, axis in CONTROL_CASES:
        taste, conc, error, ms = await _extract(provider, text)
        crowd = [p for p in _CROWD_PATTERNS if re.search(p, taste)] if taste else []
        if axis == "concentration":
            # 순수 혼잡도 발화: 혼잡도 축이 켜지고 taste에 혼잡도 단어가 안 남으면
            # 통과다. "활기찬" 같은 진짜 취향 단어가 taste에 남는 건 오염이 아니다.
            ok = conc in _SCORING_INTENTS and not crowd
        else:
            ok = bool(taste) and conc not in _SCORING_INTENTS
        control_rows.append(
            {
                "발화": text,
                "축": axis,
                "taste": taste if taste else "null",
                "혼잡도": conc if conc else "null",
                "일치": error is None and ok,
                "혼잡누출": crowd,
                "오류": error,
                "ms": ms,
            }
        )
        print("." if error is None else "!", end="", flush=True)
        await asyncio.sleep(delay)

    print(flush=True)
    return {"taste": taste_rows, "overlap": overlap_rows, "control": control_rows}


def _report(groups: dict[str, list[dict[str, object]]]) -> int:
    failures = 0

    print("\n■ 취향 추출 (taste pass/fail)")
    print(f"{'기대':<5} {'일치':<5} {'혼잡도':<8} {'발화':<30} {'taste_query'}")
    print("-" * 92)
    for r in groups["taste"]:
        ok = "✅" if r["일치"] and not r["누출"] and not r["혼잡누출"] else "❌"
        if ok == "❌":
            failures += 1
        print(f"{r['기대']:<5} {ok:<4} {str(r['혼잡도']):<8} {r['발화']:<30} {r['taste']}")
        if r["누출"]:
            print(f"{'':>11} ⚠️  조건 누출: {r['누출']}")
        if r["혼잡누출"]:
            print(f"{'':>11} ⚠️  혼잡도 단어 누출: {r['혼잡누출']}")
        if r["오류"]:
            print(f"{'':>11} ⚠️  {r['오류']}")

    print("\n■ 겹침 측정 (핵심: 혼잡도 단어가 taste_query에 남는가 / 참고: co-fill)")
    print(f"{'누출':<5} {'혼잡도':<8} {'발화':<30} {'taste_query'}")
    print("-" * 92)
    co_fill = 0
    crowd_leak = 0
    for r in groups["overlap"]:
        leaked = bool(r["혼잡누출"])
        mark = "❌" if leaked else "✅"
        if leaked:
            crowd_leak += 1
        if r["동시"]:
            co_fill += 1
        print(f"{mark:<4} {str(r['혼잡도']):<8} {r['발화']:<30} {r['taste']}")
        if r["오류"]:
            print(f"{'':>11} ⚠️  {r['오류']}")
    total_overlap = len(groups["overlap"])
    print(f"\n  → 혼잡도 단어 누출 {crowd_leak}/{total_overlap}건 (목표 0)")
    print(f"  → 참고: co-fill(두 축 동시) {co_fill}/{total_overlap}건 "
          "— 취향 단어가 따로 있으면 정당하므로 0일 필요는 없다")

    print("\n■ 대조군 (한 축만 나와야 함)")
    print(f"{'축':<14} {'일치':<5} {'혼잡도':<8} {'발화':<24} {'taste_query'}")
    print("-" * 92)
    for r in groups["control"]:
        ok = "✅" if r["일치"] else "❌"
        if ok == "❌":
            failures += 1
        print(f"{r['축']:<14} {ok:<4} {str(r['혼잡도']):<8} {r['발화']:<24} {r['taste']}")
        if r["혼잡누출"]:
            print(f"{'':>15} ⚠️  혼잡도 단어 누출: {r['혼잡누출']}")
        if r["오류"]:
            print(f"{'':>15} ⚠️  {r['오류']}")

    print(
        f"\n실패(취향+대조군) {failures}건 · "
        f"겹침 혼잡도 단어 누출 {crowd_leak}/{total_overlap}건(목표 0) · "
        f"참고 co-fill {co_fill}/{total_overlap}건"
    )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="모델 이름(기본: 설정값)")
    parser.add_argument("--delay", type=float, default=1.0, help="호출 간 대기(초)")
    args = parser.parse_args()

    groups = asyncio.run(run(args.model, args.delay))
    raise SystemExit(1 if _report(groups) else 0)


if __name__ == "__main__":
    main()
