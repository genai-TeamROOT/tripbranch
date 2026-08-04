"""TourAPI 원본 응답을 공통 PlaceCandidate 모델로 변환하는 매퍼.

역할: TourAPI locationBasedList2의 item(dict)을 PlaceCandidate로 정규화한다.
입력: TourAPI 응답의 item 딕셔너리 1건.
출력: PlaceCandidate 모델.
호출 시점: RealPlaceProvider가 API 응답을 순회하며 각 item에 대해 호출한다.
TODO: detailIntro2 연동 후 operating_hours를 실제 값으로 채운다.
"""

from __future__ import annotations

from app.schemas import PlaceCandidate, PlaceType

# TourAPI contenttypeid → PlaceType. LLM이 조건으로 내려보내는 어휘와 같아야 조회와
# 응답의 왕복이 맞는다. 역방향은 category_rules.PLACE_TYPE_TO_CONTENT_TYPE_ID에 있다.
_CONTENT_TYPE_TO_CATEGORY = {
    "12": PlaceType.ATTRACTION.value,          # 관광지
    "14": PlaceType.CULTURAL_FACILITY.value,   # 문화시설
    "15": PlaceType.FESTIVAL.value,            # 축제공연행사
    "28": PlaceType.LEISURE.value,             # 레포츠
    "38": PlaceType.SHOPPING.value,            # 쇼핑
    "39": PlaceType.RESTAURANT.value,          # 음식점
}

# LLM이 요청할 수 없는 유형이라 추천 후보로 쓰지 않는다. 유형·태그 조건이 있으면
# contentTypeId로 걸러져 애초에 오지 않지만, 조건 없는 무분류 조회에는 섞여 들어온다
# (0802 종로구 스냅샷 기준 숙박 88건, 여행코스 0건).
_UNSUPPORTED_CONTENT_TYPE_IDS = frozenset({"25", "32"})


def map_tour_api_item(item: dict) -> PlaceCandidate | None:
    """TourAPI item 1건을 PlaceCandidate로 변환. 필수 필드 없으면 None 반환."""
    content_id = item.get("contentid")
    title = item.get("title")
    map_x = item.get("mapx")  # 경도
    map_y = item.get("mapy")  # 위도

    if not content_id or not title or not map_x or not map_y:
        return None  # 필수 정보 없는 항목은 후보에서 제외

    try:
        longitude = float(map_x)
        latitude = float(map_y)
    except (TypeError, ValueError):
        return None

    content_type_id = str(item.get("contenttypeid", ""))
    if content_type_id in _UNSUPPORTED_CONTENT_TYPE_IDS:
        return None
    category = _CONTENT_TYPE_TO_CATEGORY.get(content_type_id, "unknown")

    address = item.get("addr1") or None
    lcls_systm1 = str(item.get("lclsSystm1", "")).strip() or None
    lcls_systm2 = str(item.get("lclsSystm2", "")).strip() or None
    lcls_systm3 = str(item.get("lclsSystm3", "")).strip() or None

    return PlaceCandidate(
        place_id=str(content_id),
        content_type_id=content_type_id or None,
        lcls_systm1=lcls_systm1,
        lcls_systm2=lcls_systm2,
        lcls_systm3=lcls_systm3,
        name=title,
        category=category,
        latitude=latitude,
        longitude=longitude,
        address=address,
        operating_hours=None,  # TODO: detailIntro2 연동 후 채움
        raw_source="tour_api",
    )


def map_tour_api_response(payload: dict) -> list[PlaceCandidate]:
    """TourAPI 전체 응답 payload에서 유효한 PlaceCandidate 목록을 추출한다."""
    try:
        items = payload["response"]["body"]["items"]
    except (KeyError, TypeError):
        return []  # 예상 구조가 아니면 빈 결과로 처리 (오류는 provider에서 별도 처리)

    # items가 빈 결과일 때 TourAPI는 "" (빈 문자열)을 주는 경우가 있어 방어
    if not items or items == "":
        return []

    raw_list = items.get("item", [])
    if isinstance(raw_list, dict):
        raw_list = [raw_list]  # 결과가 1건이면 dict로 오는 경우 방어

    candidates = [map_tour_api_item(raw) for raw in raw_list]
    return [c for c in candidates if c is not None]
