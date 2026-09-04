"""저장된 취향 칩 → 취향 질의 변환 규칙을 못 박는다(D 영역).

실제 저장 데이터(`user_preferences.items`)의 모양을 그대로 쓴다 — 칩은
`{label, source, codes}` 세 필드다.
"""

from __future__ import annotations

import pytest

from app.domain.saved_preference import to_taste_query, usable_chips
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


def test_발화에_취향이_있으면_저장값을_쓰지_않는다() -> None:
    """합치지 않는다 — 모순을 걸러낼 방법이 없다(모듈 docstring).

    합치는 쪽이 점수는 높았지만(0.29 → 0.43), 방금 한 말을 흐리지 않는다.
    """
    assert to_taste_query(_SAVED_B, spoken_taste_query="조용한 카페") is None


@pytest.mark.parametrize("spoken", ["", "   ", None])
def test_발화_취향이_비어_있으면_저장값을_쓴다(spoken: str | None) -> None:
    """공백만 있는 값도 "말하지 않음"으로 본다."""
    result = to_taste_query(_SAVED_B, spoken_taste_query=spoken)

    assert result == "혼자 가기 좋은 사진 명소 힙한 분위기"


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
