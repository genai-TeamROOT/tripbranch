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

# 원문에 붙어 오는 출처 표시. 뜻이 없는 꼬리라 그대로 내보내면 화면에도 답변에도
# `"엘리베이터 있음_무장애 편의시설"`처럼 읽힌다. 원문 15종을 통틀어 835곳에 있고
# 종류는 세 가지다 — `_무장애 편의시설`(619) · `_시각장애인 편의시설`(208) ·
# `_무장애 편의정보`(8). 분류명을 열거하지 않고 자리로 찾는 이유는 새 분류가
# 붙어도 같은 모양이기 때문이다(2026-09-04 서울 25개 구 실측).
#
# 꼬리 뒤에 설명이 이어지는 값도 3곳 있다("…_무장애 편의시설지상 공터에 주차하는
# 것이 더 편리함"). 지우는 자리에 공백을 넣어 그 설명이 앞말과 붙지 않게 한다.
_SOURCE_TAG_PATTERN = re.compile(r"_[가-힣]+ 편의(?:시설|정보)")

# 두 문장이 구분자 없이 붙어 온 자리. `"영유아거치대 있음기저귀교환대 있음"`처럼
# 앞 문장의 `있음` 뒤에 곧바로 다음 문장이 시작한다(실측 18건, `있음에도` 같은
# 어미 활용은 한 건도 없어 문장 경계로 봐도 안전하다).
_GLUED_SENTENCE_PATTERN = re.compile(r"있음(?=[가-힣])")

# 수유실 값이 비어도 기저귀교환대는 `infant_family_etc_raw`에 들어 있다. 실측
# 70건이 이 필드에서만 기저귀를 말하고, 그중 48건은 수유실 값이 아예 없다 —
# 수유실만 보면 그 48곳에서 기저귀 갈 곳이 있다는 사실이 사라진다.
_DIAPER_KEYWORD = "기저귀"

# `disability_etc_raw`는 잡동사니 필드지만 231건 중 142건이 좌석 형태를 말한다.
# 나머지에는 `"공연장까지 이동하는 경로에 2~3단 정도의 계단이 있음"`처럼 단차
# 서술이 섞여 있어(19건) 통째로 내면 카드에서 뺀 축이 되돌아온다. 좌석을 말하는
# 값만 고르며, 그 값에 단차 서술이 함께 들어 있는 행은 실측 0건이었다.
_SEATING_KEYWORDS = ("의자식", "입식")


def clean_barrier_free_text(value: object) -> str | None:
    """무장애 원문을 사람이 읽을 수 있는 한 문장으로 다듬는다.

    `clean_text`가 하는 태그·공백 정리에 더해 두 가지를 고친다 — 출처 표시를 떼고,
    구분자 없이 붙어 온 문장을 나눈다. 둘 다 원문의 뜻은 바꾸지 않는다.

    적재 쪽(`providers/tour_barrier_free.py`)이 아니라 여기서 하는 이유는 그 모듈이
    원문을 그대로 저장하기로 정해 두었기 때문이다. 해석은 소비 측 몫이다.
    """
    cleaned = clean_text(value)
    if cleaned is None:
        return None
    without_tag = _SOURCE_TAG_PATTERN.sub(" ", cleaned)
    separated = _GLUED_SENTENCE_PATTERN.sub(
        f"있음{_WHEELCHAIR_ACCESS_SEPARATOR}", without_tag
    )
    return _WHITESPACE_PATTERN.sub(" ", separated).strip() or None


def _joined_barrier_free(*values: str | None) -> str | None:
    """여러 원문을 한 값으로 잇는다. 전부 비면 None이다."""
    parts = [
        cleaned for cleaned in (clean_barrier_free_text(value) for value in values)
        if cleaned is not None
    ]
    if not parts:
        return None
    return _WHEELCHAIR_ACCESS_SEPARATOR.join(parts)


def compose_visual_guide(details: PlaceDetails) -> str | None:
    """점자블록·점자 안내물·음성 안내를 한 값으로 잇는다.

    셋을 따로 두지 않는 이유는 채움률이다. 개별로는 6~17%라 카드에서 세 줄 중
    두 줄이 늘 비지만, 합치면 무장애 정보가 있는 1,229곳 중 296곳(24%)에서 한
    줄이라도 나온다(2026-09-04 실측). 시각장애 동행에게는 세 값이 "안내를 받을
    수단이 있는가"라는 하나의 답을 이룬다.
    """
    return _joined_barrier_free(
        details.braille_block_raw,
        details.braille_promotion_raw,
        details.audio_guide_raw,
    )


def compose_nursing_room(details: PlaceDetails) -> str | None:
    """수유실과 기저귀교환대를 한 값으로 잇는다.

    기저귀교환대가 수유실 필드가 아니라 영유아·가족 편의 필드에 들어 있어서다.
    영유아 필드에 기저귀 언급이 없으면(유아용 식기 등) 빼고 수유실만 낸다 —
    "수유·기저귀" 줄에 식기 얘기가 붙으면 라벨과 값이 어긋난다.
    """
    infant_family = clean_barrier_free_text(details.infant_family_etc_raw)
    if infant_family is not None and _DIAPER_KEYWORD not in infant_family:
        infant_family = None
    return _joined_barrier_free(details.nursing_room_raw, infant_family)


def compose_seating(details: PlaceDetails) -> str | None:
    """장애인 편의 기타에서 좌석 형태를 말하는 값만 고른다.

    의자식(입식) 테이블이 있다는 것은 좌식이 아니라는 뜻이라, 오래 앉아 있기
    어려운 동행에게 쓸모가 있다.
    """
    disability_etc = clean_barrier_free_text(details.disability_etc_raw)
    if disability_etc is None:
        return None
    if not any(keyword in disability_etc for keyword in _SEATING_KEYWORDS):
        return None
    return disability_etc


def resolve_stroller_rental(details: PlaceDetails) -> tuple[str | None, str | None]:
    """(무장애 유모차 대여, detailIntro2 유모차) 중 쓸 값을 정한다.

    두 필드가 같은 사실을 말하는데 서로 어긋난다 — 둘 다 값이 있는 34곳 중
    21곳(62%)에서 detailIntro2는 `"없음"`·`"불가"`인데 무장애 원문은
    `"대여가능"`이다(서울공예박물관·국립현대미술관 서울·스타필드 코엑스몰 등,
    2026-09-04 서울 25개 구 실측). 무장애 쪽이 대수·위치·조건까지 적어 더
    구체적이므로 그쪽이 있으면 그쪽만 쓰고, 없을 때만 detailIntro2 값을 남긴다.

    둘을 함께 내면 카드가 "유모차: 없음"과 "유모차 대여: 대여가능(10대)"을 나란히
    보여준다.
    """
    stroller_rental = clean_barrier_free_text(details.stroller_rental_raw)
    if stroller_rental is not None:
        return stroller_rental, None
    return None, clean_text(details.baby_carriage)


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
    return _joined_barrier_free(
        details.approach_route_raw,
        details.entrance_access_raw,
        details.elevator_raw,
    )


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
        # 유모차는 반대다. detailIntro2와 detailWithTour2가 같은 사실을 말하는데
        # 값이 서로 어긋나 하나만 골라야 한다 — 규칙과 근거는
        # resolve_stroller_rental()에 있다.
        stroller_rental, baby_carriage = resolve_stroller_rental(details)
        fields = _normalized(
            ("baby_carriage", baby_carriage),
            ("pet", details.pet),
            ("credit_card", details.credit_card),
            ("restroom", details.restroom),
        )
        # 무장애 원문은 출처 꼬리·붙은 문장을 정리해 낸다. 답변과 상세 카드가 같은
        # 원문을 서로 다르게 다듬으면 같은 장소가 두 자리에서 다르게 읽힌다.
        fields.update(
            _normalized(
                ("wheelchair_access", _compose_wheelchair_access(details)),
                ("accessible_restroom", clean_barrier_free_text(details.accessible_restroom_raw)),
                ("accessible_parking", clean_barrier_free_text(details.accessible_parking_raw)),
                ("wheelchair_rental", clean_barrier_free_text(details.wheelchair_rental_raw)),
                ("stroller_rental", stroller_rental),
                ("nursing_room", clean_barrier_free_text(details.nursing_room_raw)),
                ("guide_dog", clean_barrier_free_text(details.guide_dog_raw)),
                ("braille_block", clean_barrier_free_text(details.braille_block_raw)),
                ("braille_promotion", clean_barrier_free_text(details.braille_promotion_raw)),
                ("audio_guide", clean_barrier_free_text(details.audio_guide_raw)),
                ("public_transport", clean_barrier_free_text(details.public_transport_raw)),
                ("infant_family_etc", clean_barrier_free_text(details.infant_family_etc_raw)),
                ("disability_etc", clean_barrier_free_text(details.disability_etc_raw)),
            )
        )
        return fields

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


__all__ = [
    "INFO_FIELD_KEYS",
    "clean_barrier_free_text",
    "clean_text",
    "compose_nursing_room",
    "compose_seating",
    "compose_visual_guide",
    "extract_info_fields",
    "resolve_stroller_rental",
]
