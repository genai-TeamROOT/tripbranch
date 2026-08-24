"""복합 취향 발화에서 한 조건이 다른 조건을 누르는 문제가 재현되는지 실측한다.

배경: "조용한 저렴한 카페"를 재봤더니 "조용한 카페" 단독 검색과 순위상관이
0.978이었다(경복궁 카페 한 곳, TP-128 착수 근거). 그런데 "저렴한"은 실제로는
taste_query가 아니라 budget 필드로 가는 말이라, 이 결과가 진짜 "취향 축 안에서
조건이 서로 누르는 문제"를 보여주는지 아니면 애초에 taste_query에 안 들어가는
말이라 안 보인 것뿐인지 구분이 안 됐다. 실제로 taste_query에 함께 들어가는
두 조건으로, 다른 카테고리에서도 같은 폭으로 재현되는지 확인한다.

방법: 카페·음식점·관광지 3개 카테고리 x 조건 조합 2개(카테고리당)를 실 LLM으로
뽑은 taste_query 문자열로 잰다. 각 조합에서
  - 복합 질의(A+B)
  - 조건 A 단독
  - 조건 B 단독
세 질의를 모두 `_enrich_taste_query()`와 같은 방식(taste_query + place_tag/
place_type 라벨)으로 보강해 실 RPC로 검색한다.

판정 지표는 **상위 5곳 중첩**이다. 사용자에게 실제로 보이는 건 상위 5곳이고,
복합 질의의 상위 5곳이 어느 한쪽 단독 질의의 상위 5곳을 그대로 베끼면 그
조건이 다른 조건을 덮은 것이다.

실패 기준: 6개 조합 중 과반에서 `overlap_a`와 `overlap_b` 중 큰 쪽이 5/5이면
"조건 지배가 카테고리를 넘어 일반적으로 재현된다"고 본다.

참고 지표 두 개 — 결론을 가르지 않는다:
  - 컷(0.43) 통과 수 — 복합이 단독보다 낮으면 그 자체로 손해다
  - 순위상관 ρ(복합, 조건A만) vs ρ(복합, 조건B만)
    ⚠️ **ρ를 판정에 쓰지 않는 이유**: 후보 수백 곳 전체를 넣고 재는 값이라
    사용자가 보지 않는 꼬리쪽 다수가 결과를 좌우한다. 실제로 이 축에서는
    ρ 0.9대가 정상 범위라, 높은 ρ 하나만 보고 "거의 같다 = 지배한다"고 읽으면
    틀린다. 이 측정의 착수 근거였던 ρ=0.978이 정확히 그 오독이었다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings
from app.providers.place_evidence import DEFAULT_MIN_SIMILARITY, PlaceEvidenceProvider
from app.providers.place_evidence_encoder import get_shared_encoder
from app.repositories.supabase_places import SupabasePlaceRepository

_RPC_TIMEOUT_SECONDS = 90.0
_ANCHOR = (37.579617, 126.977041)  # 경복궁 — 상한 초과 시 자르는 기준점
_PAGE_SIZE = 1000
_MAX_CANDIDATES = 500
_MIN_MATCHED = 5

_CAFE_SMALL_CODE = "FD050100"
_RESTAURANT_CONTENT_TYPE_ID = "39"
_ATTRACTION_CONTENT_TYPE_ID = "12"

# 전부 실 LLM(gemini-3.5-flash-lite)이 "<A>하고 <B> <카테고리> 추천해줘"에서
# 실제로 뽑은 taste_query다 — budget/companion으로 안 새는 것을 확인했다
# (2026-08-24, scripts 실행 로그 참고). "라벨"은 _enrich_taste_query()가
# 실제로 붙이는 place_tag/place_type 라벨과 같다.
@dataclass(frozen=True)
class ConditionCombo:
    category: str
    label: str  # 검색 질의에 붙는 place_tag/place_type 라벨
    condition_a: str
    condition_b: str


_COMBOS: tuple[ConditionCombo, ...] = (
    ConditionCombo("카페", "카페", "조용한", "감성적인"),
    ConditionCombo("카페", "카페", "아늑한", "사진 찍기 좋은"),
    ConditionCombo("음식점", "맛집", "조용한", "분위기 좋은"),
    ConditionCombo("음식점", "맛집", "한적한", "가족끼리 가기 좋은"),
    ConditionCombo("관광지", "관광지", "고즈넉한", "볼거리 많은"),
    ConditionCombo("관광지", "관광지", "조용한", "화려한"),
)

RESULTS_DIR = Path(__file__).resolve().parents[1] / "test_results"
RESULTS_CSV = RESULTS_DIR / "taste_condition_dominance.csv"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
        * math.sin(d_lng / 2) ** 2
    )
    return radius * 2 * math.asin(math.sqrt(a))


async def _fetch_places(client: httpx.AsyncClient) -> list[dict[str, object]]:
    """활성 장소를 전부 읽는다(PostgREST가 한 번에 1000행까지만 준다)."""
    places: list[dict[str, object]] = []
    offset = 0
    while True:
        response = await client.get(
            "/rest/v1/places",
            params={
                "select": "content_id,latitude,longitude,lcls_systm3,content_type_id",
                "is_active": "eq.true",
                "limit": str(_PAGE_SIZE),
                "offset": str(offset),
            },
        )
        response.raise_for_status()
        batch = response.json()
        for row in batch:
            content_id, lat, lng = row.get("content_id"), row.get("latitude"), row.get("longitude")
            if content_id and lat is not None and lng is not None:
                places.append(
                    {
                        "content_id": str(content_id),
                        "latitude": float(lat),
                        "longitude": float(lng),
                        "lcls_systm3": row.get("lcls_systm3"),
                        "content_type_id": str(row.get("content_type_id") or ""),
                    }
                )
        if len(batch) < _PAGE_SIZE:
            return places
        offset += _PAGE_SIZE


def _candidates_for(places: list[dict[str, object]], category: str) -> list[str]:
    if category == "카페":
        keep = lambda p: p["lcls_systm3"] == _CAFE_SMALL_CODE  # noqa: E731
    elif category == "음식점":
        keep = lambda p: p["content_type_id"] == _RESTAURANT_CONTENT_TYPE_ID  # noqa: E731
    elif category == "관광지":
        keep = lambda p: p["content_type_id"] == _ATTRACTION_CONTENT_TYPE_ID  # noqa: E731
    else:
        raise ValueError(f"알 수 없는 카테고리: {category}")

    matched = [
        (_haversine_km(_ANCHOR[0], _ANCHOR[1], p["latitude"], p["longitude"]), p)
        for p in places
        if keep(p)
    ]
    matched.sort(key=lambda entry: entry[0])
    return [str(p["content_id"]) for _, p in matched[:_MAX_CANDIDATES]]


def _spearman(a: dict[str, float], b: dict[str, float]) -> float:
    keys = sorted(set(a) & set(b))
    if len(keys) < 4:
        return float("nan")

    def ranks(scores: dict[str, float]) -> dict[str, int]:
        order = sorted(keys, key=lambda k: -scores[k])
        return {k: i for i, k in enumerate(order)}

    ra, rb = ranks(a), ranks(b)
    xs = [ra[k] for k in keys]
    ys = [rb[k] for k in keys]
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)
    )
    return numerator / denominator if denominator else float("nan")


_TOP_N = 5


def _top_ids(scores: dict[str, float], n: int = _TOP_N) -> list[str]:
    """유사도 내림차순 상위 n곳. 동점은 content_id로 갈라 실행마다 같은 순서를 준다."""
    return sorted(scores, key=lambda k: (-scores[k], k))[:n]


@dataclass(frozen=True)
class DominanceRow:
    category: str
    condition_a: str
    condition_b: str
    candidate_count: int
    passed_compound: int
    passed_a: int
    passed_b: int
    # 판정 지표 — 복합 상위 5곳 중 각 단독 상위 5곳과 겹치는 수.
    overlap_a: int
    overlap_b: int
    # 복합에만 있는 곳. 5 - (a∪b와의 겹침)이라 overlap 합과 일치하지 않을 수 있다.
    novel_in_compound: int
    # 참고 지표 — 꼬리까지 포함한 값이라 판정에 쓰지 않는다(docstring 참고).
    rho_compound_vs_a: float
    rho_compound_vs_b: float
    dominant: str
    gap: float


async def run(delay: float) -> list[DominanceRow]:
    settings = Settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise ValueError("SUPABASE_URL / SUPABASE_SECRET_KEY가 필요합니다.")

    encoder = get_shared_encoder()
    encoder.warmup()
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
    }
    rows: list[DominanceRow] = []
    async with httpx.AsyncClient(
        base_url=settings.supabase_url.rstrip("/"),
        headers=headers,
        timeout=_RPC_TIMEOUT_SECONDS,
    ) as client:
        places = await _fetch_places(client)
        repository = SupabasePlaceRepository(
            supabase_url=settings.supabase_url,
            secret_key=settings.supabase_secret_key,
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
        provider = PlaceEvidenceProvider(encoder, repository, min_similarity=0.0)

        for combo in _COMBOS:
            candidates = _candidates_for(places, combo.category)
            if len(candidates) < _MIN_MATCHED:
                print(f"[건너뜀] {combo.category}: 후보 {len(candidates)}곳뿐")
                continue

            compound_query = f"{combo.condition_a}하고 {combo.condition_b} {combo.label}"
            a_query = f"{combo.condition_a} {combo.label}"
            b_query = f"{combo.condition_b} {combo.label}"

            compound = await provider.search(compound_query, candidates)
            await asyncio.sleep(delay)
            a_only = await provider.search(a_query, candidates)
            await asyncio.sleep(delay)
            b_only = await provider.search(b_query, candidates)
            await asyncio.sleep(delay)

            vc = {k: m.avg_similarity for k, m in compound.data.items()}
            va = {k: m.avg_similarity for k, m in a_only.data.items()}
            vb = {k: m.avg_similarity for k, m in b_only.data.items()}
            if len(vc) < _MIN_MATCHED:
                print(f"[건너뜀] {combo.category} '{compound_query}': 매칭 {len(vc)}곳뿐")
                continue

            rho_a = _spearman(vc, va)
            rho_b = _spearman(vc, vb)
            gap = abs(rho_a - rho_b)

            top_c = _top_ids(vc)
            top_a, top_b = set(_top_ids(va)), set(_top_ids(vb))
            overlap_a = sum(1 for k in top_c if k in top_a)
            overlap_b = sum(1 for k in top_c if k in top_b)
            novel = sum(1 for k in top_c if k not in top_a and k not in top_b)
            # 지배 판정은 상위 5곳 기준이다. 동수면 지배라고 부르지 않는다.
            if overlap_a == overlap_b:
                dominant = "-"
            else:
                dominant = (
                    combo.condition_a if overlap_a > overlap_b else combo.condition_b
                )

            rows.append(
                DominanceRow(
                    category=combo.category,
                    condition_a=combo.condition_a,
                    condition_b=combo.condition_b,
                    candidate_count=len(candidates),
                    passed_compound=sum(1 for v in vc.values() if v >= DEFAULT_MIN_SIMILARITY),
                    passed_a=sum(1 for v in va.values() if v >= DEFAULT_MIN_SIMILARITY),
                    passed_b=sum(1 for v in vb.values() if v >= DEFAULT_MIN_SIMILARITY),
                    overlap_a=overlap_a,
                    overlap_b=overlap_b,
                    novel_in_compound=novel,
                    rho_compound_vs_a=rho_a,
                    rho_compound_vs_b=rho_b,
                    dominant=dominant,
                    gap=gap,
                )
            )
    return rows


def _print(rows: list[DominanceRow]) -> None:
    header = (
        f"{'카테고리':<8} {'조건A':<10} {'조건B':<14} {'후보':>4} "
        f"{'복합':>4} {'A단독':>5} {'B단독':>5} {'겹A':>4} {'겹B':>4} {'신규':>4} "
        f"{'지배':<10} {'ρ(A)':>6} {'ρ(B)':>6}"
    )
    print(header)
    print("-" * len(header))
    dominated = 0
    for r in rows:
        print(
            f"{r.category:<8} {r.condition_a:<10} {r.condition_b:<14} "
            f"{r.candidate_count:>4} {r.passed_compound:>4} {r.passed_a:>5} "
            f"{r.passed_b:>5} {r.overlap_a:>4} {r.overlap_b:>4} "
            f"{r.novel_in_compound:>4} {r.dominant:<10} "
            f"{r.rho_compound_vs_a:>6.3f} {r.rho_compound_vs_b:>6.3f}"
        )
        if max(r.overlap_a, r.overlap_b) >= _TOP_N:
            dominated += 1
    print()
    print(
        f"판정 — 상위 {_TOP_N}곳이 한쪽 단독과 완전히 같은 조합: "
        f"{dominated}/{len(rows)} (과반이면 조건 지배 재현)"
    )
    print(
        "참고 — ρ는 후보 전체 기준이라 꼬리쪽 다수에 좌우된다. 판정에 쓰지 않는다."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=1.0, help="RPC 호출 간 대기(초)")
    args = parser.parse_args()

    rows = asyncio.run(run(args.delay))
    _print(rows)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "category",
                "condition_a",
                "condition_b",
                "candidate_count",
                "passed_compound",
                "passed_a",
                "passed_b",
                "overlap_a",
                "overlap_b",
                "novel_in_compound",
                "dominant",
                "rho_compound_vs_a",
                "rho_compound_vs_b",
                "gap",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.category,
                    r.condition_a,
                    r.condition_b,
                    r.candidate_count,
                    r.passed_compound,
                    r.passed_a,
                    r.passed_b,
                    r.overlap_a,
                    r.overlap_b,
                    r.novel_in_compound,
                    r.dominant,
                    f"{r.rho_compound_vs_a:.4f}",
                    f"{r.rho_compound_vs_b:.4f}",
                    f"{r.gap:.4f}",
                ]
            )
    print(f"\n결과 저장: {RESULTS_CSV}")


if __name__ == "__main__":
    main()
