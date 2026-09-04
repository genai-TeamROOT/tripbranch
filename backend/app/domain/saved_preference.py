"""계정에 저장해 둔 취향 칩을 채점 입력으로 옮긴다.

취향 설정 화면에서 고른 칩(`state.UserPreference`)은 그동안 저장만 되고 추천에
실리지 않았다(`state/preferences.py` 모듈 주석). 이 모듈이 그 값을 취향 근거
검색 질의로 바꾼다 — **무엇을 점수 입력으로 쓸지는 채점 규칙이라 D가 정한다.**
읽어서 넘기는 배선은 A가 한다(`agent_runtime.py`).

순수 함수만 둔다. 저장소도 설정도 보지 않으므로 칩 목록만 있으면 테스트된다.

## 발화가 있으면 저장값을 쓰지 않는다

이번 턴에 취향을 말했으면 그것이 지금 원하는 것이다. 저장값은 "말하지 않았을
때의 기본값"이지 발화에 덧붙이는 값이 아니다 — 합치면 "조용한 곳"을 저장한
사람이 "시끄러운 데 가고 싶어"라고 할 때 두 말이 한 질의에 섞인다.

실측으로는 합치는 쪽이 점수가 높았다(취향점수 중앙 0.29 → 0.43, 종로·중구 500곳).
그래도 안 합치는 이유는 **모순을 걸러낼 방법이 없기 때문**이다. 점수를 얻자고
사용자가 방금 한 말을 흐리지 않는다.

## 고른 칩은 종류를 가리지 않고 전부 넣는다

화면이 최소 3개·최대 5개를 고르게 하므로(`PreferencesPage.tsx`), **고른 것을
버리면 사용자가 고른 수만큼 반영되지 않는다.** 처음에는 분류(`place_tag`)와 동행
칩을 걸렀는데, 실제 저장값으로 재보니 그 필터가 손해였다 — 종로·중구 500곳:

| 저장값 | 전부 | 동행만 제외 | 동행+분류 제외 |
| --- | --- | --- | --- |
| 분류 3개가 섞인 5개 | 0.33 | 0.39 | **0.22** (칩 1개만 남음) |
| 분류 위주 5개 | 0.52 | 0.52 | **0.26** (칩 1개만 남음) |
| 분위기 위주 5개 | 0.51 | 0.51 | 0.51 |

분류 칩을 빼면 5개를 고른 사람의 질의가 1개짜리가 되고, 칩이 적을수록 점수가
낮다(1개 0.31 → 5개 0.63). **분류 칩을 질의에 넣는 것과 하드 필터로 쓰는 것은
다르다** — 여기서는 순위만 다듬고 후보를 지우지 않으므로 "그 분류만 나온다"는
위험이 생기지 않는다.

동행 칩("친구와 함께" 등)은 단독 통과율이 2.4~10.0%로 낮고 좋은 조합에 붙이면
점수를 깎는다(0.46 → 0.25~0.30). 그래도 넣는 이유는 **화면이 동행 칩을 최대 1개로
제한할 예정이라 최악이 1개뿐이고, 동행만 고른 사용자가 취향을 아예 못 쓰는 것보다는
낫기 때문**이다. 그 제한이 들어오기 전에 여러 개를 저장한 사용자는 그만큼 손해를
보는데, 다시 고르면 정리되는 값이라 백엔드에서 자르지 않는다(2026-09-04 팀 결정).

## 5개를 고르면 5개가 모두 맞는 곳만 나오는 게 아니다

라벨을 공백으로 이어 **벡터 하나로** 검색한다. AND도 OR도 아니고 "합친 말에 가까운
곳"이다 — 후보 500곳 실측에서 5개 전부 맞는 곳은 35곳인데 이 방식은 318곳이
걸렸다(하나라도 맞는 곳은 337곳).

칩마다 따로 검색해 최댓값을 쓰는 방식도 재봤으나 택하지 않았다. 그쪽은 칩 하나만
세게 맞는 곳이 이겨서 취향점수 중앙이 0.43으로 낮았다(합친 질의 0.51). 여러 칩에
골고루 맞는 곳이 위로 오는 편이 5개를 고른 뜻에 가깝고, 검색도 한 번이면 된다.

**아무 칩에도 안 걸린 후보가 추천에서 빠지지는 않는다.** 취향은 순위를 다듬는 축이라
근거가 없으면 0.0점일 뿐이고(`scoring.py::_taste_score`), 날씨·영업시간이 좋으면
그대로 올라온다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

# 화면 칩의 출처(`frontend/src/pages/preferenceOptions.ts`).
# - preference: 리뷰·블로그에서 뽑은 장소별 취향 태그(`place_preference_tags`)
# - place_tag: TourAPI 소분류. **질의에는 넣되 하드 필터로는 절대 쓰지 않는다**
# - custom: 사용자가 직접 적은 키워드. 대응 코드가 없어 codes가 빈 배열이다
# 화면이 아는 출처만 질의에 넣는다. 새 종류가 생기면 **그 값을 여기 적기 전까지
# 채점이 조용히 먹지 않는다** — 화면이 칩을 늘렸는데 점수가 따라 바뀌면 무엇 때문에
# 순위가 달라졌는지 로그로 못 찾는다.
_QUERY_SOURCES = frozenset({"preference", "place_tag", "custom"})


class SavedPreferenceChip(Protocol):
    """`state.schema.UserPreference`가 만족하는 최소 계약.

    B의 모델을 직접 import 하지 않는다 — D 도메인이 상태 계층에 의존하면 채점
    규칙을 테스트하는 데 저장소 스키마가 딸려 온다.
    """

    label: str
    source: str
    codes: list[str]


def usable_chips(chips: Iterable[SavedPreferenceChip]) -> list[SavedPreferenceChip]:
    """질의에 쓸 칩만 고른다. 고른 순서를 유지한다.

    순서를 지키는 이유는 사용자가 고른 순서가 곧 우선순위로 읽히기 때문이다
    (`state/schema.py::UserPreferenceList` 주석). 질의 문자열에서 앞에 오는 말이
    임베딩에 더 세게 걸리는지는 재보지 않았지만, 순서를 흔들 근거도 없다.
    """
    return [chip for chip in chips if chip.source in _QUERY_SOURCES and chip.label.strip()]


def to_taste_query(
    chips: Sequence[SavedPreferenceChip],
    *,
    spoken_taste_query: str | None = None,
) -> str | None:
    """저장된 칩을 취향 근거 검색 질의로 바꾼다. 쓸 것이 없으면 `None`.

    `spoken_taste_query`가 있으면 **저장값을 쓰지 않고 `None`을 돌려준다** —
    이번 턴에 말한 것이 우선이고, 호출부는 발화 질의를 그대로 쓰면 된다.
    합치지 않는 이유는 이 모듈 docstring에 있다.

    `None`과 빈 문자열을 구분한다. `None`은 "취향 축을 쓰지 않는다"로 이어지고,
    빈 문자열은 검색을 돌려 근거 0건을 만든다 — 후자는 전 후보가 0점인 축을
    켜서 다른 축의 몫만 깎는다(`scoring.py::_taste_score` 주석).

    라벨을 그대로 쓰고 `codes`는 쓰지 않는다. 코드는 영어라 한국어 임베딩과 맞지
    않는다 — 종로·중구 500곳 실측에서 `healing` 2.6% 대 "힐링하기 좋은" 52.4%,
    `cozy` 13.8% 대 "아늑한 공간" 53.0%였다.
    """
    if spoken_taste_query and spoken_taste_query.strip():
        return None

    labels = [chip.label.strip() for chip in usable_chips(chips)]
    if not labels:
        return None
    return " ".join(labels)


__all__ = ["SavedPreferenceChip", "to_taste_query", "usable_chips"]
