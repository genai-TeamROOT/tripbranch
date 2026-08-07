"""INFO question_type별로 PlaceDetails에서 답변에 쓸 필드를 뽑는 규칙.

TourAPI detailIntro2는 contentTypeId마다 같은 의미의 필드 이름이 다르다 —
운영시간 하나가 ``usetime``/``usetimeculture``/``opentime``/``playtime``으로
흩어져 있다. 이 모듈은 유형별 후보 키를 순서대로 훑어 처음 발견한 값을 쓰고,
소비 측에는 C가 고정한 정규화 키(INFO_FIELD_KEYS)로만 넘긴다.

real_place.py가 운영시간·휴무일에 대해 이미 같은 방식(_OPERATING_HOURS_KEYS)을
쓰고 있고, 이 모듈은 그 대상을 나머지 question_type으로 넓힌 것이다.

값 정제는 두 가지만 한다 — HTML 태그 제거와 공백 정리. 문구를 지어내거나
"정보 없음" 같은 기본값을 채우지 않는다. 값이 없으면 키 자체를 넣지 않는다.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping

from app.agent_context.info_schemas import InfoQuestionType
from app.domain.models import PlaceDetails

# 소비 측(A)이 읽는 정규화 키. 이 이름이 계약이다 — TourAPI 원본 키를 그대로
# 노출하지 않는다.
INFO_FIELD_KEYS = {
    "operating_hours": "operating_hours",
    "rest_date": "rest_date",
    "fee": "fee",
    "parking": "parking",
    "parking_fee": "parking_fee",
    "baby_carriage": "baby_carriage",
    "pet": "pet",
    "credit_card": "credit_card",
    "restroom": "restroom",
    "address": "address",
    "telephone": "telephone",
    "overview": "overview",
    "homepage": "homepage",
}

# (정규화 키, detailIntro2 후보 키들). 앞에서부터 값이 있는 첫 키를 채택한다.
_FEE_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fee", ("usefee", "usefeeleports", "usetimefestival")),
)
_PARKING_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "parking",
        (
            "parking",
            "parkingculture",
            "parkingleports",
            "parkingshopping",
            "parkingfood",
            "parkinglodging",
        ),
    ),
    ("parking_fee", ("parkingfee", "parkingfeeleports", "parkingfeeculture")),
)
_FACILITY_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "baby_carriage",
        (
            "chkbabycarriage",
            "chkbabycarriageculture",
            "chkbabycarriageleports",
            "chkbabycarriageshopping",
        ),
    ),
    ("pet", ("chkpet", "chkpetculture", "chkpetleports", "chkpetshopping")),
    (
        "credit_card",
        (
            "chkcreditcard",
            "chkcreditcardculture",
            "chkcreditcardleports",
            "chkcreditcardshopping",
            "chkcreditcardfood",
        ),
    ),
    ("restroom", ("restroom",)),
)

_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_text(value: object) -> str | None:
    """TourAPI 텍스트에서 HTML 태그를 벗기고 공백을 정리한다.

    overview는 <br>로 줄바꿈이 들어오고 일부 필드는 &amp; 같은 엔티티가 섞인다.
    태그를 지울 때 <br>을 공백으로 바꾸지 않으면 앞뒤 단어가 붙어버린다.
    """
    if not isinstance(value, str):
        return None
    unescaped = html.unescape(_TAG_PATTERN.sub(" ", value))
    normalized = _WHITESPACE_PATTERN.sub(" ", unescaped).strip()
    return normalized or None


def _first_present(
    source: Mapping[str, object], candidate_keys: tuple[str, ...]
) -> str | None:
    for key in candidate_keys:
        cleaned = clean_text(source.get(key))
        if cleaned is not None:
            return cleaned
    return None


def _collect(
    source: Mapping[str, object],
    rules: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[str, str]:
    fields: dict[str, str] = {}
    for normalized_key, candidate_keys in rules:
        value = _first_present(source, candidate_keys)
        if value is not None:
            fields[normalized_key] = value
    return fields


def extract_info_fields(
    question_type: InfoQuestionType,
    details: PlaceDetails,
) -> dict[str, str]:
    """question_type이 필요로 하는 필드만 뽑는다. 없으면 빈 dict를 돌려준다.

    concentration은 이 경로를 타지 않는다(집중률 API 전용 경로).
    """

    if question_type == "operating_hours":
        # 운영시간·휴무일은 provider가 이미 유형별 키를 훑어 정규화해둔 값이 있다.
        # Supabase 경로도 이 두 필드는 채우므로 여기서 raw_intro를 다시 보지 않는다.
        fields: dict[str, str] = {}
        operating_hours = clean_text(details.operating_hours)
        if operating_hours is not None:
            fields["operating_hours"] = operating_hours
        rest_date = clean_text(details.rest_date)
        if rest_date is not None:
            fields["rest_date"] = rest_date
        return fields

    if question_type == "fee":
        return _collect(details.raw_intro, _FEE_KEYS)

    if question_type == "parking":
        return _collect(details.raw_intro, _PARKING_KEYS)

    if question_type == "facility":
        return _collect(details.raw_intro, _FACILITY_KEYS)

    if question_type == "location_info":
        fields = {}
        address = clean_text(details.address)
        if address is not None:
            fields["address"] = address
        telephone = clean_text(details.telephone)
        if telephone is not None:
            fields["telephone"] = telephone
        return fields

    if question_type == "general_info":
        fields = {}
        overview = clean_text(details.overview)
        if overview is not None:
            fields["overview"] = overview
        homepage = clean_text(details.homepage)
        if homepage is not None:
            fields["homepage"] = homepage
        return fields

    # event(searchFestival2 별도 연동 필요)와 concentration은 호출부가 걸러낸다.
    return {}


__all__ = ["INFO_FIELD_KEYS", "clean_text", "extract_info_fields"]
