"""저장된 취향 칩 → 취향 질의 변환 규칙을 못 박는다(D 영역).

실제 저장 데이터(`user_preferences.items`)의 모양을 그대로 쓴다 — 칩은
`{label, source, codes}` 세 필드다.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.domain.saved_preference import (
    _CHIP_AXIS_VALUES,
    chip_axis_value,
    spoken_axis_values,
    to_taste_query,
    usable_chips,
)
from app.state.schema import UserPreference


def _chip(label: str, source: str, *codes: str) -> UserPreference:
    return UserPreference(label=label, source=source, codes=list(codes))


# DB에 실제로 저장돼 있던 값(2026-09-04 조회). 지어내지 않는다.
_SAVED_A = [
    _chip("힐링하기 좋은", "preference", "healing"),
    _chip("카페", "place_tag", "카페", "찻집"),
    _chip("혼자 가기 좋은", "preference", "alone"),
]
_SAVED_B = [
    _chip("혼자 가기 좋은", "preference", "alone"),
    _chip("사진 명소", "preference", "photo_spot"),
    _chip("힙한 분위기", "preference", "trendy_hotspot"),
]


def test_저장된_칩의_라벨을_공백으로_잇는다() -> None:
    assert to_taste_query(_SAVED_B) == "혼자 가기 좋은 사진 명소 힙한 분위기"


def test_고른_순서를_지킨다() -> None:
    """사용자가 고른 순서가 곧 우선순위로 읽힌다(state/schema.py 주석)."""
    reversed_chips = list(reversed(_SAVED_B))

    assert to_taste_query(reversed_chips) == "힙한 분위기 사진 명소 혼자 가기 좋은"


def test_고른_칩을_하나도_버리지_않는다() -> None:
    """화면이 최소 3개·최대 5개를 고르게 한다. 걸러내면 고른 수만큼 반영되지 않는다.

    분류 칩을 뺐을 때 5개짜리 저장값의 질의가 1개로 줄어 취향점수가 0.39 → 0.22로
    떨어졌다(종로·중구 500곳). 분류 칩을 **질의에 넣는 것**과 **하드 필터로 쓰는
    것**은 다르다 — 여기서는 순위만 다듬고 후보를 지우지 않는다.
    """
    five = [
        _chip("사진 명소", "preference", "photo_spot"),
        _chip("전시·문화", "place_tag", "박물관", "미술관"),
        _chip("시장·쇼핑", "place_tag", "시장"),
        _chip("전통·역사", "place_tag", "궁궐"),
        _chip("친구와 함께", "preference", "with_friends"),
    ]

    assert to_taste_query(five) == "사진 명소 전시·문화 시장·쇼핑 전통·역사 친구와 함께"
    assert len(usable_chips(five)) == 5


def test_발화에_취향이_있어도_안_겹치는_칩은_남는다() -> None:
    """발화가 정본이지만 저장값을 통째로 버리지는 않는다.

    발화 "조용한 카페"는 혼잡도 축만 정한다. 동행·분위기 칩은 부딪히지 않으므로
    그대로 남아 발화 뒤에 붙는다.
    """
    result = to_taste_query(
        _SAVED_B, spoken_taste_query="조용한 카페", concentration_intent="AVOID"
    )

    # "힙한 분위기"만 혼잡도 축(SEEK)이라 빠진다.
    assert result == "혼자 가기 좋은 사진 명소"


@pytest.mark.parametrize("spoken", ["", "   ", None])
def test_발화_취향이_비어_있으면_저장값을_쓴다(spoken: str | None) -> None:
    """공백만 있는 값도 "말하지 않음"으로 본다."""
    result = to_taste_query(_SAVED_B, spoken_taste_query=spoken)

    assert result == "혼자 가기 좋은 사진 명소 힙한 분위기"


def test_발화가_정한_축의_칩만_빠진다() -> None:
    """축이 없는 칩은 발화가 무엇을 정하든 절대 안 빠진다."""
    result = to_taste_query(
        _SAVED_B,
        spoken_taste_query="조용한",
        concentration_intent="AVOID",
        environment="indoor",
        companion="solo",
    )

    # 혼자 가기 좋은(동행 solo·중복) + 힙한 분위기(혼잡도 SEEK·모순)가 빠지고
    # 어느 축도 아닌 "사진 명소"만 남는다.
    assert result == "사진 명소"


def test_place_tag_칩도_질의에_넣는다() -> None:
    """하드 필터로는 안 쓰지만 질의에는 넣는다 — 빼면 고른 수만큼 반영되지 않는다."""
    assert to_taste_query(_SAVED_A) == "힐링하기 좋은 카페 혼자 가기 좋은"


@pytest.mark.parametrize(
    "code", ["alone", "date", "with_friends", "with_kids", "with_parents", "group_gathering"]
)
def test_동행_칩도_질의에_넣는다(code: str) -> None:
    """단독 통과율이 2.4~10.0%로 낮고 좋은 조합에 붙이면 점수를 깎지만(0.46 →
    0.25~0.30), 화면이 동행 칩을 최대 1개로 제한할 예정이라 최악이 1개뿐이고
    동행만 고른 사용자가 취향을 아예 못 쓰는 것보다 낫다(2026-09-04 팀 결정).
    """
    chips = [_chip("분위기 칩", "preference", "cozy"), _chip("동행 칩", "preference", code)]

    assert to_taste_query(chips) == "분위기 칩 동행 칩"


def test_동행_칩만_저장해도_취향_축을_쓴다() -> None:
    chips = [_chip(label, "preference", code) for label, code in
             (("혼자 가기 좋은", "alone"), ("데이트 코스", "date"))]

    assert to_taste_query(chips) == "혼자 가기 좋은 데이트 코스"


def test_직접_입력한_키워드는_넣는다() -> None:
    """custom은 대응 코드가 없어 codes가 빈 배열이다."""
    chips = [_chip("루프탑", "custom")]

    assert to_taste_query(chips) == "루프탑"


def test_알_수_없는_source는_넣지_않는다() -> None:
    """화면이 칩 종류를 늘려도 채점이 조용히 그 값을 먹지 않게 한다."""
    chips = [_chip("무언가", "brand_new_source", "x")]

    assert to_taste_query(chips) is None


def test_라벨이_공백뿐인_칩은_버린다() -> None:
    chips = [_chip("   ", "preference", "cozy"), _chip("아늑한 공간", "preference", "cozy")]

    assert to_taste_query(chips) == "아늑한 공간"


def test_고른_적이_없으면_None() -> None:
    assert to_taste_query([]) is None


def test_usable_chips는_칩_객체를_그대로_돌려준다() -> None:
    """호출부가 라벨 말고 다른 필드도 볼 수 있게 원본을 유지한다."""
    picked = usable_chips(_SAVED_A)

    assert [chip.label for chip in picked] == ["힐링하기 좋은", "카페", "혼자 가기 좋은"]
    assert picked[0].codes == ["healing"]


# --- 발화와 겹치거나 부딪히는 칩 빼기 ---------------------------------------
#
# 규칙 하나로 중복과 모순을 함께 뺀다: 값이 다르면 항상, 같으면 발화 취향이
# 있을 때만. 아래 표가 그 두 갈래를 각각 못 박는다.

_QUIET = _chip("조용한 곳", "preference", "quiet")
_TRENDY = _chip("힙한 분위기", "preference", "trendy_hotspot")
_NATURE = _chip("자연·공원", "place_tag", "공원", "산", "호수", "계곡", "수목원")
_ANY_WEATHER = _chip("날씨 상관없는 곳", "preference", "indoor")
_WITH_KIDS = _chip("아이와 함께", "preference", "with_kids")
_PHOTO = _chip("사진 명소", "preference", "photo_spot")


@pytest.mark.parametrize(
    ("chip", "axis_kwargs"),
    [
        (_QUIET, {"concentration_intent": "SEEK"}),
        (_TRENDY, {"concentration_intent": "AVOID"}),
        (_NATURE, {"environment": "indoor"}),
        (_ANY_WEATHER, {"environment": "outdoor"}),
        (_WITH_KIDS, {"companion": "solo"}),
    ],
)
def test_모순되는_칩은_발화_취향이_없어도_뺀다(
    chip: UserPreference, axis_kwargs: dict[str, str]
) -> None:
    """모순은 항상 뺀다.

    발화 취향이 없어도 뺀다 — "혼자 갈 데"에 "아이와 함께"를 밀어 올릴 이유가
    어느 경우에도 없다. 실측에서 모순 칩을 합치면 결과가 뒤집혔다: "북적이는
    활기찬" + 조용한 곳 칩 → 포장마차·빈대떡이 안국선원·박물관·화랑으로 바뀌었다.
    """
    assert to_taste_query([chip, _PHOTO], **axis_kwargs) == "사진 명소"


@pytest.mark.parametrize(
    ("chip", "axis_kwargs"),
    [
        (_QUIET, {"concentration_intent": "AVOID"}),
        (_TRENDY, {"concentration_intent": "SEEK"}),
        (_NATURE, {"environment": "outdoor"}),
        (_ANY_WEATHER, {"environment": "indoor"}),
        (_WITH_KIDS, {"companion": "child"}),
    ],
)
def test_같은_값인_칩은_발화_취향이_있을_때만_뺀다(
    chip: UserPreference, axis_kwargs: dict[str, str]
) -> None:
    """중복은 발화 질의에 그 말이 이미 있을 때만 뺀다.

    발화 취향이 없으면 남긴다 — "아이랑 갈 데 추천"은 companion=child를 채우지만
    taste_query가 null이라(`extract.md`: 동행 표현은 취향 서술과 함께 나올 때만
    남는다), 칩까지 빼면 질의 어디에도 아이가 남지 않는다.
    """
    kept = to_taste_query([chip, _PHOTO], **axis_kwargs)
    dropped = to_taste_query([chip, _PHOTO], spoken_taste_query="분위기 좋은", **axis_kwargs)

    assert kept == f"{chip.label} 사진 명소"
    assert dropped == "사진 명소"


@pytest.mark.parametrize(
    "axis_kwargs",
    [
        {"concentration_intent": "IGNORE"},
        {"concentration_intent": None},
        {"environment": "any"},
        {"environment": None},
        {"companion": None},
    ],
)
def test_상관없다고_말한_축은_칩을_빼지_않는다(axis_kwargs: dict[str, str | None]) -> None:
    """IGNORE·any는 "확정"이 아니다.

    "사람 많아도 괜찮아"(IGNORE)는 조용한 곳을 원하지 않는다는 말이 아니다
    (`prompts/_shared/rules/concentration_intent.md`).
    """
    chips = [_QUIET, _NATURE, _WITH_KIDS]

    result = to_taste_query(chips, spoken_taste_query="분위기 좋은", **axis_kwargs)

    assert result == "조용한 곳 자연·공원 아이와 함께"


def test_place_tag_칩은_코드_하나만_걸려도_축이_잡힌다() -> None:
    """"자연·공원"은 코드가 다섯이다. 먼저 걸리는 코드로 축을 정한다."""
    assert chip_axis_value(_NATURE) == ("environment", "outdoor")


@pytest.mark.parametrize(
    "chip",
    [
        _PHOTO,
        _chip("아늑한 공간", "preference", "cozy"),
        _chip("카페", "place_tag", "카페", "찻집"),
        _chip("단체 모임", "preference", "group_gathering"),
        _chip("루프탑", "custom"),
    ],
)
def test_축을_안_붙인_칩은_절대_안_빠진다(chip: UserPreference) -> None:
    """애매한 칩은 일부러 축을 비워 뒀다(모듈 `_CHIP_AXIS_VALUES` 주석).

    "단체 모임"은 `Companion` 어휘에 대응 값이 없어 어느 쪽으로 넣어도 틀리는
    경우가 생긴다. 재보기 전에는 안 붙인다.
    """
    result = to_taste_query(
        [chip],
        spoken_taste_query="분위기 좋은",
        concentration_intent="AVOID",
        environment="indoor",
        companion="solo",
    )

    assert result == chip.label


def test_남는_칩이_없으면_None() -> None:
    """전부 빠지면 빈 문자열이 아니라 None이다.

    빈 문자열은 호출부가 취향 축을 켜서 전 후보가 0점인 축이 다른 축의 몫만
    깎는다(`scoring.py::_taste_score`).
    """
    assert to_taste_query([_QUIET], concentration_intent="SEEK") is None


def test_spoken_axis_values는_확정된_축만_담는다() -> None:
    assert spoken_axis_values(
        concentration_intent="IGNORE", environment="any", companion="solo"
    ) == {"companion": "solo"}


# --- 화면 칩 목록과 축 표가 어긋나지 않게 ------------------------------------


def test_화면_칩_코드가_전부_축_표에_판정돼_있다() -> None:
    """칩이 늘면 여기서 깨진다.

    축 표(`_CHIP_AXIS_VALUES`)는 화면 카탈로그
    (`frontend/src/pages/preferenceOptions.ts`)의 복제라 어긋날 수 있다. 백엔드가
    프론트 파일을 읽는 게 흔한 모양은 아니지만, **칩이 축 없이 조용히 늘어나는
    것**을 잡을 방법이 이것뿐이다 — 축이 없으면 모순 칩이 그대로 질의에 섞인다.

    새 코드를 추가할 때는 축을 붙이거나, 붙이지 않기로 했으면 그 이유를
    `_UNTAGGED_ON_PURPOSE`에 적는다.
    """
    catalog = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend/src/pages/preferenceOptions.ts"
    )
    if not catalog.exists():  # 백엔드만 체크아웃한 경우
        pytest.skip(f"프론트 카탈로그 없음: {catalog}")

    codes = {
        code
        for block in re.findall(r"codes:\s*\[([^\]]*)\]", catalog.read_text())
        for code in re.findall(r'"([^"]+)"', block)
    }
    assert codes, "카탈로그에서 코드를 하나도 못 읽었다 — 파싱이 깨졌다"

    unjudged = codes - set(_CHIP_AXIS_VALUES) - _UNTAGGED_ON_PURPOSE
    assert not unjudged, f"축 판정이 없는 새 칩 코드: {sorted(unjudged)}"


# 축을 **일부러** 안 붙인 코드. 이유는 `_CHIP_AXIS_VALUES` 주석에 있다 —
# 요약하면 "그 축으로 기울 뿐 그 축을 말하는 칩은 아니다"이다.
_UNTAGGED_ON_PURPOSE = frozenset(
    {
        # 분위기 — 조용한 쪽으로 기울지만 혼잡도를 말한 칩은 아니다
        "photo_spot", "healing", "unique", "cozy", "good_view", "night_visit",
        "spacious", "reading",
        # 테마 — 실내가 많을 뿐 실내외를 말한 칩이 아니다(테라스 카페·전통시장)
        "박물관", "미술관", "전시관", "전시회", "카페", "찻집",
        "시장", "쇼핑몰", "백화점",
        "궁궐", "사찰", "성곽", "전통체험", "마을",
        "experience", "food_exploration",
        # 동행 — `Companion` 어휘에 대응 값이 없다
        "group_gathering",
    }
)
