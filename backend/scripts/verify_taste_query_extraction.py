"""RECOMMEND 조건 추출이 취향 발화만 taste_query에 담는지 실 LLM으로 검증한다.

프롬프트 스냅샷 테스트는 지시문 문자열만 고정할 뿐 모델이 그 지시를 따르는지는
보지 않는다. 이 스크립트는 실제로 호출해서 두 가지를 확인한다.

1. 취향 발화 -> taste_query가 채워지고, 시간·거리 조건이 섞이지 않는가
2. 비취향 발화(일정·거리·장소유형) -> taste_query가 null인가

2번이 특히 중요하다. 실측(2026-08-19)에서 "3시간 안에 다녀올 수 있는 곳"이
취향 근거 검색에서 유사도 0.523으로 진짜 취향 발화(0.498)보다 높게 나왔다 —
이 문장이 taste_query에 담기면 엉뚱한 장소에 취향 점수가 붙는다.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import time

from app.config import Settings
from app.providers.gemini import RealGeminiProvider

# (발화, taste_query가 채워져야 하는가)
CASES: tuple[tuple[str, bool], ...] = (
    # --- 취향 발화: 채워져야 한다 ---
    ("혼자 조용히 쉴 만한 곳 추천해줘", True),
    ("부모님이랑 갈 만한 분위기 좋은 곳", True),
    ("감성적인 사진 찍기 좋은 데 알려줘", True),
    ("빈티지하고 레트로한 분위기 카페", True),
    ("사람 많은 곳 말고 한적한 데로", True),
    ("친구들이랑 시끌벅적하게 놀 만한 곳", True),
    # --- 비취향: null이어야 한다 ---
    ("3시간 안에 다녀올 수 있는 곳", False),
    ("지하철역에서 가까운 곳", False),
    ("반나절 코스로 짜줘", False),
    ("종로 맛집 추천", False),
    ("걸어서 20분 이내로", False),
    ("경복궁 근처 추천해줘", False),
    # --- 혼합: 취향만 뽑고 시간·거리는 빼야 한다 ---
    ("3시간 안에 갈 수 있는 조용한 카페", True),
    ("지하철역 가까우면서 분위기 좋은 곳", True),
)

# taste_query에 섞이면 안 되는 표현. 다른 필드가 이미 받는 조건들이다.
# 부분 문자열로 찾으면 "분위기"의 "분"을 시간 조건으로 오탐하므로 패턴으로 잡는다.
_LEAK_PATTERNS = (
    r"\d+\s*(시간|분|km|킬로|미터|m)\b",   # 3시간, 20분, 2km
    r"반나절|코스|일정",                      # 일정 조건
    r"지하철|역에서|도보로|걸어서",             # 교통·거리 조건
    r"\d+\s*(명|인)",                      # 인원
)


async def run(model: str | None, delay: float) -> list[dict[str, object]]:
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

    results: list[dict[str, object]] = []
    for text, should_fill in CASES:
        started = time.perf_counter()
        try:
            result = await provider.extract_recommend_conditions(text)
            recommend = result.data.recommend
            conditions = recommend.conditions if recommend else None
            taste = conditions.taste_query if conditions else None
            error = None
        except Exception as exc:  # noqa: BLE001 - 실 API 검증 스크립트
            taste, error = None, f"{type(exc).__name__}: {exc}"

        filled = bool(taste)
        leaked = (
            [p for p in _LEAK_PATTERNS if re.search(p, taste)] if taste else []
        )
        results.append(
            {
                "발화": text,
                "기대": "채움" if should_fill else "null",
                "실제": taste if taste else "null",
                "일치": error is None and filled == should_fill,
                "누출": leaked,
                "오류": error,
                "ms": round((time.perf_counter() - started) * 1000),
            }
        )
        print("." if error is None else "!", end="", flush=True)
        await asyncio.sleep(delay)
    print(flush=True)
    return results


def _report(results: list[dict[str, object]]) -> int:
    print(f"\n{'기대':<5} {'일치':<5} {'발화':<32} {'taste_query'}")
    print("-" * 92)
    failures = 0
    for r in results:
        ok = "✅" if r["일치"] and not r["누출"] else "❌"
        if ok == "❌":
            failures += 1
        print(f"{r['기대']:<5} {ok:<4} {r['발화']:<32} {r['실제']}")
        if r["누출"]:
            print(f"{'':>11} ⚠️  조건 누출: {r['누출']}")
        if r["오류"]:
            print(f"{'':>11} ⚠️  {r['오류']}")

    total = len(results)
    print(f"\n통과 {total - failures}/{total}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="모델 이름(기본: 설정값)")
    parser.add_argument("--delay", type=float, default=1.0, help="호출 간 대기(초)")
    args = parser.parse_args()

    results = asyncio.run(run(args.model, args.delay))
    raise SystemExit(1 if _report(results) else 0)


if __name__ == "__main__":
    main()
