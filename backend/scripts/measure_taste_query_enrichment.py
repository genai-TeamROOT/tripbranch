"""place_tag를 붙인 taste 질의가 실제로 컷 통과율을 올리는지 실측한다.

배경: `real_recommendation_provider._taste_matches_for()`가 뽑아 쓰는
`taste_query`는 extract.md 규칙상 "조용한"처럼 단어 하나로 오는 경우가
많다(HISTORY.md 2.3.0). 단어 하나짜리 질의는 문장형 리뷰 텍스트와 임베딩이
잘 안 맞아서, 실제로는 관련 있는 근거인데도 컷(0.43)을 못 넘는 경우가 많다.

지역·카테고리 하드 필터가 이미 "이 후보는 카페다"를 알고 있으므로, 그 값을
질의에 붙이면("조용한" → "조용한 카페") 새 정보 없이 검색 정확도를 올릴 수
있다는 게 가설이다. 이 스크립트는 그 가설을 실측한다.

방법: 중심점 4곳(종로 4개 지점, taste_score_distribution.csv와 같은 지점
기준) 반경 3km 안의 실제 카페(TourAPI 소분류 FD050100) 전체를 후보로 잡고,
"조용한"(원문 그대로) vs "조용한 <place_tag>"(제안하는 방식)의 컷 통과율·평균
유사도를 비교한다.
"""

from __future__ import annotations

import asyncio
import csv
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings
from app.providers.place_evidence import DEFAULT_MIN_SIMILARITY, PlaceEvidenceProvider
from app.providers.place_evidence_encoder import get_shared_encoder
from app.repositories.supabase_places import SupabasePlaceRepository

_RPC_TIMEOUT_SECONDS = 90.0

_CENTERS: dict[str, tuple[float, float]] = {
    "경복궁": (37.579617, 126.977041),
    "종각": (37.5701, 126.9829),
    "혜화": (37.5823743, 127.0014404),
    "부암동": (37.5924, 126.9634),
}
_RADIUS_KM = 3.0
_CAFE_SMALL_CODE = "FD050100"
_BASE_QUERY = "조용한"
_CAFE_TAG = "카페"

RESULTS_DIR = Path(__file__).resolve().parents[1] / "test_results"
RESULTS_CSV = RESULTS_DIR / "taste_query_enrichment.csv"


@dataclass(frozen=True)
class EnrichmentRow:
    center: str
    query: str
    candidate_count: int
    matched: int
    passed_cut: int
    avg_similarity: float


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


async def _fetch_cafes(client: httpx.AsyncClient) -> list[tuple[str, float, float]]:
    response = await client.get(
        "/rest/v1/places",
        params={
            "select": "content_id,latitude,longitude,lcls_systm3",
            "is_active": "eq.true",
            "limit": "1000",
        },
    )
    response.raise_for_status()
    cafes: list[tuple[str, float, float]] = []
    for row in response.json():
        if row.get("lcls_systm3") != _CAFE_SMALL_CODE:
            continue
        content_id, lat, lng = row.get("content_id"), row.get("latitude"), row.get("longitude")
        if content_id and lat is not None and lng is not None:
            cafes.append((str(content_id), float(lat), float(lng)))
    return cafes


async def run(centers: dict[str, tuple[float, float]]) -> list[EnrichmentRow]:
    settings = Settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise ValueError("SUPABASE_URL / SUPABASE_SECRET_KEY가 필요합니다.")

    encoder = get_shared_encoder()
    encoder.warmup()

    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
    }
    rows: list[EnrichmentRow] = []
    async with httpx.AsyncClient(
        base_url=settings.supabase_url.rstrip("/"),
        headers=headers,
        timeout=_RPC_TIMEOUT_SECONDS,
    ) as client:
        all_cafes = await _fetch_cafes(client)
        repository = SupabasePlaceRepository(
            supabase_url=settings.supabase_url,
            secret_key=settings.supabase_secret_key,
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
        # p_min_similarity=0.0으로 전체 분포를 받아서, 컷(DEFAULT_MIN_SIMILARITY)
        # 적용 여부를 이쪽에서 판단한다 — 실제 서비스 컷과 다른 값을 실험할 때도
        # RPC를 다시 부르지 않아도 된다.
        provider = PlaceEvidenceProvider(encoder, repository, min_similarity=0.0)

        for center_name, center in centers.items():
            candidates = [
                content_id
                for content_id, lat, lng in all_cafes
                if _haversine_km(center[0], center[1], lat, lng) <= _RADIUS_KM
            ]
            for query in (_BASE_QUERY, f"{_BASE_QUERY} {_CAFE_TAG}"):
                result = await provider.search(query, candidates)
                matches = list(result.data.values())
                passed = sum(
                    1 for m in matches if m.avg_similarity >= DEFAULT_MIN_SIMILARITY
                )
                avg_sim = statistics.mean(m.avg_similarity for m in matches) if matches else 0.0
                rows.append(
                    EnrichmentRow(
                        center=center_name,
                        query=query,
                        candidate_count=len(candidates),
                        matched=len(matches),
                        passed_cut=passed,
                        avg_similarity=avg_sim,
                    )
                )
    return rows


def _print(rows: Sequence[EnrichmentRow]) -> None:
    header = f"{'중심':<6} {'질의':<14} {'후보':>4} {'매칭':>4} {'컷통과':>5} {'평균유사':>8}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r.center:<6} {r.query:<14} {r.candidate_count:>4} {r.matched:>4} "
            f"{r.passed_cut:>5} {r.avg_similarity:>8.4f}"
        )


def main() -> None:
    rows = asyncio.run(run(_CENTERS))
    _print(rows)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            ["center", "query", "candidate_count", "matched", "passed_cut", "avg_similarity"]
        )
        for r in rows:
            writer.writerow(
                [
                    r.center,
                    r.query,
                    r.candidate_count,
                    r.matched,
                    r.passed_cut,
                    f"{r.avg_similarity:.4f}",
                ]
            )
    print(f"\n결과 저장: {RESULTS_CSV}")


if __name__ == "__main__":
    main()
