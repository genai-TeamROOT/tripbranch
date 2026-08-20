"""사용자 발화로 취향 근거 문장을 벡터 검색하는 Provider.

역할: 발화를 임베딩해 `search_place_evidence` RPC를 부르고, 후보별 근거를
      돌려준다. 추천 점수에 "취향" 축을 더하기 위한 입력이다.

입력: 취향 질의 문장, 하드 필터를 통과한 후보 content_id 목록.
출력: content_id를 키로 하는 PlaceEvidenceMatch dict.
호출 시점: 하드 필터 이후, 채점 전.

**후보를 반드시 좁혀서 부른다.** RPC가 500건 상한을 강제하고, 좁히지 않으면
40,389행을 전부 훑어 6~9초가 걸린다(2026-08-18 실측).

임베딩 인코더는 Protocol로 주입받는다. `sentence-transformers`가 선택
의존성(`pip install -e ".[embeddings]"`)이라 기본 설치에는 없고, 모델을 서버에
상주시킬지가 배포 메모리(RSS 약 1.2GB) 결정에 달려 있기 때문이다. 인코더가
없는 환경에서는 이 Provider를 조립하지 않으면 되고, 테스트는 torch 없이 돈다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.domain.models import PlaceEvidenceMatch
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.repositories.protocols import PlaceEvidenceRepository

# 유사도 컷값. 대표 발화 11개의 유사도 분포를 재서 정했다(2026-08-18, RAG 계획
# 문서 §7.13). RPC 기본값은 0.0이라 호출부가 넘기지 않으면 필터가 걸리지 않는다.
DEFAULT_MIN_SIMILARITY = 0.43

# 장소당 남길 근거 문장 수. 근거 문장 한 줄을 만들기에 3개면 충분하고, 늘리면
# jsonb 응답만 커진다.
DEFAULT_MATCH_COUNT = 3


class PlaceEvidenceEncoder(Protocol):
    """취향 질의 문장을 적재 때와 같은 벡터 공간으로 인코딩하는 계약.

    적재는 `jhgan/ko-sroberta-multitask`(768차원, 정규화 임베딩)로 했다. 다른
    모델로 인코딩하면 유사도가 의미를 잃으므로 구현체는 같은 모델을 써야 한다.
    """

    def encode(self, text: str) -> Sequence[float]: ...


class PlaceEvidenceProvider:
    """발화 → 임베딩 → RPC 검색을 한 번에 처리한다."""

    def __init__(
        self,
        encoder: PlaceEvidenceEncoder,
        repository: PlaceEvidenceRepository,
        *,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        match_count: int = DEFAULT_MATCH_COUNT,
    ) -> None:
        self._encoder = encoder
        self._repository = repository
        self._min_similarity = min_similarity
        self._match_count = match_count

    async def search(
        self,
        query: str,
        candidate_content_ids: Sequence[str],
    ) -> ProviderResult[dict[str, PlaceEvidenceMatch]]:
        """취향 질의로 후보 범위 안에서만 근거를 찾는다.

        질의가 비었거나 후보가 없으면 인코딩도 조회도 하지 않는다 — 취향을
        말하지 않은 요청이 대부분이라, 여기서 걸러야 모델 호출이 낭비되지 않는다.
        """
        if not query.strip() or not candidate_content_ids:
            return provider_result(
                {},
                source=ProviderSource.SUPABASE_PLACE_EVIDENCE,
                status=ProviderStatus.NO_DATA,
            )

        embedding = self._encoder.encode(query)
        matches = await self._repository.search_place_evidence(
            embedding,
            candidate_content_ids,
            match_count=self._match_count,
            min_similarity=self._min_similarity,
        )
        return provider_result(
            {match.content_id: match for match in matches},
            source=ProviderSource.SUPABASE_PLACE_EVIDENCE,
            status=(
                ProviderStatus.SUCCESS if matches else ProviderStatus.NO_DATA
            ),
        )
