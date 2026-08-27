"""사진으로 분위기가 닮은 장소를 찾는 API.

`POST /api/places/similar-by-photo`는 사진 한 장과 위치를 받아, 그 주변에서
분위기가 닮은 장소를 유사도 순으로 돌려준다.

**인텐트를 타지 않는다.** 인텐트는 "사용자 발화가 무엇을 원하는가"를 분류하는
장치인데, 사진은 발화가 아니라 이미 목적이 확정된 입력이다. 음성 전사
(`/api/transcribe`)가 같은 이유로 인텐트 밖에 있다.

**추천 채점을 타지 않는다.** 순위는 사진 유사도만으로 정한다. 거리·취향·혼잡도를
섞지 않으므로 `domain/scoring.py`를 건드리지 않는다(D-094 후속, TP-175).
다만 하드 필터는 태운다 — 지금 닫힌 가게가 1등으로 나오면 쓸모가 없다.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from app.auth.dependency import OptionalPrincipal
from app.errors import AppError
from app.observability.api_usage import create_external_client
from app.providers.factory import (
    get_geocoding_provider,
    get_place_mood_provider,
    get_place_provider,
)
from app.schemas import PhotoSimilarPlace, PhotoSimilarPlacesResponse
from app.services.photo_similar import PhotoSimilarQuery, build_photo_similar_places

router = APIRouter(tags=["photo-similar"])

# 사진 한 장의 상한. 휴대폰 원본 사진이 10MB를 넘는 경우가 있어 넉넉히 두되,
# 임베딩은 224x224로 줄여 쓰므로 그보다 큰 파일을 받을 이유는 없다.
_MAX_IMAGE_BYTES = 10 * 1024 * 1024

# 브라우저가 보내는 형식만 받는다. SigLIP 인코더가 Pillow로 열어 RGB로 바꾸므로
# 형식 자체는 더 넓게 되지만, 받는 범위를 좁혀 두면 예상 못 한 입력이 모델까지
# 내려가지 않는다.
_ALLOWED_MIME_TYPES = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}
)

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 30


@router.post("/places/similar-by-photo", response_model=PhotoSimilarPlacesResponse)
async def similar_by_photo(
    principal: OptionalPrincipal,
    image: Annotated[UploadFile, File(description="분위기를 찾을 사진")],
    location_query: Annotated[str | None, Form(description='지역명. 예: "성수동"')] = None,
    latitude: Annotated[float | None, Form(description="기기 GPS 위도")] = None,
    longitude: Annotated[float | None, Form(description="기기 GPS 경도")] = None,
    search_radius_km: Annotated[float | None, Form(description="검색 반경(km)")] = None,
    limit: Annotated[int, Form(description="돌려줄 장소 수")] = _DEFAULT_LIMIT,
) -> PhotoSimilarPlacesResponse:
    """사진과 위치를 받아 분위기가 닮은 장소를 찾는다.

    위치는 `location_query`가 있으면 그것으로 풀고, 없으면 좌표를 그대로 쓴다.
    **지역명이 좌표를 이긴다** — 사용자가 적은 쪽이 의도이고 좌표는 적지 않았을
    때의 기본값이다. 둘 다 없으면 `location_required`로 되묻는다.

    사진은 저장하지 않는다. 요청 메모리에서 임베딩만 하고 버린다.
    """
    mime_type = (image.content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if mime_type not in _ALLOWED_MIME_TYPES:
        raise AppError(
            code="unsupported_image_format",
            message="지원하지 않는 사진 형식이에요. JPG나 PNG로 올려 주세요.",
            status_code=415,
        )

    image_bytes = await image.read()
    if not image_bytes:
        raise AppError(
            code="empty_image",
            message="사진이 비어 있어요. 다시 올려 주세요.",
            status_code=422,
            retryable=True,
        )
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise AppError(
            code="image_too_large",
            message="사진이 너무 커요. 10MB 이하로 올려 주세요.",
            status_code=413,
        )

    started = time.perf_counter()
    async with create_external_client() as client:
        result = await build_photo_similar_places(
            PhotoSimilarQuery(
                image_bytes=image_bytes,
                location_query=(location_query or "").strip() or None,
                latitude=latitude,
                longitude=longitude,
                search_radius_km=search_radius_km,
                limit=max(1, min(limit, _MAX_LIMIT)),
            ),
            geocoding_provider=get_geocoding_provider(client),
            place_provider=get_place_provider(client),
            mood_provider=get_place_mood_provider(client),
        )

    return PhotoSimilarPlacesResponse(
        places=[
            PhotoSimilarPlace(
                content_id=row.content_id,
                title=row.name,
                similarity=row.similarity,
                photo_count=row.photo_count,
            )
            for row in result.places
        ],
        center_name=result.center_name,
        candidate_count=result.candidate_count,
        truncated_count=result.truncated_count,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
