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
    # 무장애 여행 정보(place_barrier_free, D-077). 무장애 목록에 등록된 장소만 값이
    # 있어 대부분의 장소에서는 이 키들이 아예 나가지 않는다(4개 구 실측 19%).
    #
    # 이름을 응답 키가 아니라 뜻으로 지었다. TourAPI의 `wheelchair`는 휠체어 출입이
    # 아니라 대여이고 `exit`는 출구가 아니라 주출입구라, 원래 키를 그대로 쓰면
    # 소비 측이 정반대로 읽는다.
    "wheelchair_access": "wheelchair_access",
    "accessible_restroom": "accessible_restroom",
    "accessible_parking": "accessible_parking",
    "wheelchair_rental": "wheelchair_rental",
    "stroller_rental": "stroller_rental",
    "nursing_room": "nursing_room",
    "guide_dog": "guide_dog",
    "braille_block": "braille_block",
    "braille_promotion": "braille_promotion",
    "audio_guide": "audio_guide",
    "public_transport": "public_transport",
    "infant_family_etc": "infant_family_etc",
    "disability_etc": "disability_etc",
    "address": "address",
    "telephone": "telephone",
    "overview": "overview",
    "homepage": "homepage",
}

# **이 모듈은 raw_intro를 더 이상 읽지 않는다.** provider가 contenttypeid별 키를 이미
# 정규화해 PlaceDetails의 fee/parking/parking_fee/baby_carriage/pet/credit_card/
# restroom에 담아두기 때문이다 — operating_hours가 진작부터 쓰던 방식이다.
#
# Supabase 캐시는 유형별 키를 한 컬럼으로 눌러 담아 raw_intro를 복원할 수 없다.
# 그 경로에서 값이 조용히 비는 것이 D-054의 원인이었고, D-060에서 이관했다.
# 옛 경로를 함께 두지 않는다 — 같은 질문이 provider에 따라 다르게 답한다.

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


def _normalized(*pairs: tuple[str, str | None]) -> dict[str, str]:
    """provider가 이미 정규화해둔 값을 계약 키로 옮긴다. 빈 값은 키 자체를 뺀다."""
    fields: dict[str, str] = {}
    for normalized_key, value in pairs:
        cleaned = clean_text(value)
        if cleaned is not None:
            fields[normalized_key] = cleaned
    return fields


_WHEELCHAIR_ACCESS_SEPARATOR = " / "


def _compose_wheelchair_access(details: PlaceDetails) -> str | None:
    """접근로·주출입구·승강기를 한 값으로 잇는다. 셋 다 비면 None이다.

    셋을 따로 내지 않고 합치는 이유는 두 가지다.

    첫째, 원문에서 접근로 설명과 출입구 설명이 서로 뒤바뀐 장소가 있다(가나아트센터는
    approach 자리에 출입구 서술이, entrance 자리에 접근로 서술이 들어 있다). 한
    값으로 합치면 그 뒤바뀜이 답변에 영향을 주지 않는다.

    둘째, "휠체어로 들어갈 수 있나요"라는 질문에는 세 값이 하나의 답을 이룬다.

    구분자를 슬래시로 둔 이유는 원문 대부분이 마침표로 끝나지 않아, 공백으로 이으면
    앞뒤 문장이 한 문장처럼 붙기 때문이다.
    """
    parts = [
        cleaned
        for cleaned in (
            clean_text(details.approach_route_raw),
            clean_text(details.entrance_access_raw),
            clean_text(details.elevator_raw),
        )
        if cleaned is not None
    ]
    if not parts:
        return None
    return _WHEELCHAIR_ACCESS_SEPARATOR.join(parts)


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
        return _normalized(("fee", details.fee))

    if question_type == "parking":
        return _normalized(
            ("parking", details.parking),
            ("parking_fee", details.parking_fee),
        )

    if question_type == "facility":
        # `없음`도 값이다 — "정보가 없다"가 아니라 "없다고 답했다"이므로 그대로 낸다.
        #
        # 무장애 값(D-077)도 여기서 함께 낸다. question_type을 새로 만들지 않은
        # 이유는 분류 규칙(prompts/info/question_type_rules.md)이 이미 "휠체어
        # 가능?"을 facility로 보내고 있어서다 — 타입을 쪼개면 "화장실 있어?"가
        # 어느 쪽인지 하는 경계만 새로 생긴다.
        #
        # 일반 화장실(restroom)과 장애인 화장실(accessible_restroom)은 뜻이 달라
        # 둘 다 낸다. 앞은 detailIntro2, 뒤는 detailWithTour2에서 온 값이다.
        #
        # 유모차는 반대다. detailIntro2의 chkbabycarriage와 detailWithTour2의
        # stroller가 같은 사실을 말하는데, 둘 다 값이 있는 6곳 중 4곳에서 서로
        # 반대다(서울공예박물관은 "없음" vs "대여가능(10대)"). 함께 내면 카드가
        # 모순된 두 줄을 보여준다. 무장애 쪽이 대수·위치·조건까지 적어 더
        # 구체적이므로 그쪽이 있으면 그쪽만 낸다.
        stroller_rental = clean_text(details.stroller_rental_raw)
        baby_carriage = None if stroller_rental else details.baby_carriage
        return _normalized(
            ("baby_carriage", baby_carriage),
            ("pet", details.pet),
            ("credit_card", details.credit_card),
            ("restroom", details.restroom),
            ("wheelchair_access", _compose_wheelchair_access(details)),
            ("accessible_restroom", details.accessible_restroom_raw),
            ("accessible_parking", details.accessible_parking_raw),
            ("wheelchair_rental", details.wheelchair_rental_raw),
            ("stroller_rental", stroller_rental),
            ("nursing_room", details.nursing_room_raw),
            ("guide_dog", details.guide_dog_raw),
            ("braille_block", details.braille_block_raw),
            ("braille_promotion", details.braille_promotion_raw),
            ("audio_guide", details.audio_guide_raw),
            ("public_transport", details.public_transport_raw),
            ("infant_family_etc", details.infant_family_etc_raw),
            ("disability_etc", details.disability_etc_raw),
        )

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
