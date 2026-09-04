"""계정에 저장해 둔 취향 칩을 채점 입력으로 옮긴다.

취향 설정 화면에서 고른 칩(`state.UserPreference`)은 그동안 저장만 되고 추천에
실리지 않았다(`state/preferences.py` 모듈 주석). 이 모듈이 그 값을 취향 근거
검색 질의로 바꾼다 — **무엇을 점수 입력으로 쓸지는 채점 규칙이라 D가 정한다.**
읽어서 넘기는 배선은 A가 한다(`agent_runtime.py`).

순수 함수만 둔다. 저장소도 설정도 보지 않으므로 칩 목록만 있으면 테스트된다.

## 발화가 정본이고, 저장 칩은 그 뒤에 붙는다

이번 턴에 말한 취향이 정본이다. 저장값은 발화를 덮지 않고 **뒤에 덧붙는다** —
질의 문자열에서 앞에 오는 말이 발화이므로 사용자가 방금 한 말이 남는다.

처음에는 발화가 있으면 저장값을 통째로 버렸다(2026-09-04 최초 구현). 합치는
쪽이 점수는 높았지만(취향점수 중앙 0.29 → 0.43, 종로·중구 500곳) **모순을 걸러낼
방법이 없어서** 버리는 쪽을 골랐었다. 실측 예:

    발화 "북적이는 활기찬 곳" + 저장 칩 "조용한 곳"
      발화만 → 순희네빈대떡, 종로3가 포장마차
      합침   → 안국선원, 북촌동양문화박물관, 선화랑   ← 조용한 곳만 나옴

아래 축 표가 그 거르는 방법이라, 이제는 합친다.

## 중복과 모순은 같은 규칙 하나로 뺀다

둘 다 "발화가 이미 정한 축을 칩이 또 건드리는 것"이다.

    발화 "조용한 곳"   + 칩 조용한 곳  →  같은 값  →  중복
    발화 "북적이는 곳" + 칩 조용한 곳  →  반대 값  →  모순

**둘 다 답이 "칩을 뺀다"로 같다.** 중복이면 발화에 이미 그 말이 있으니 빼도
손해가 없고, 모순이면 빼야 한다. 그래서 임계값도 임베딩 비교도 쓰지 않는다 —
칩이 어느 축인지만 알면 된다.

임베딩 유사도로 거르는 안은 **반대말을 못 잡아서** 기각했다. "조용한 곳"과
"혼자 조용히 쉴 만한"은 0.694로 붙지만 "조용한 곳"과 "북적이는 활기찬"은
0.186으로 오히려 **멀다** — 모순일수록 유사도가 낮아 임계값으로는 안 걸린다.

## 발화가 그 축을 정했는지는 LLM이 이미 답해 뒀다

`concentration_intent`·`environment`·`companion`은 `recommend.extract`가 매 턴
뽑는 값이다. 여기서는 **읽기만 한다** — 프롬프트를 건드리지 않으므로 같은 요청에
항상 같은 결과가 나오고, 프롬프트 버전을 올릴 일도 없다.

`environment`가 날씨로도 채워지는 것(`extract.md`: weather_intent가 AVOID/ENJOY면
environment도 함께 채운다)은 여기서 이득이다 — 비 오는 날 요청에서 "자연·공원"
칩이 저절로 빠진다.

## 모순은 항상 빼고, 중복은 발화에 취향이 있을 때만 뺀다

같은 값인 칩을 언제나 빼면 **발화 질의가 비어 있을 때 신호가 통째로 사라진다.**
"아이랑 갈 데 추천"은 `companion=child`를 채우지만 취향 서술이 없어
`taste_query`가 null이다(`extract.md`: 동행 표현은 *취향 서술과 함께 나올 때*
taste_query에 남는다). 여기서 "아이와 함께" 칩까지 빼면 질의에 아이가 사라진다.

그래서 같은 값은 **발화 취향이 있을 때만** 뺀다. 그때는 그 말이 이미 발화 질의
안에 있다. 다른 값(모순)은 발화 취향 유무와 무관하게 뺀다 — "혼자 갈 데"에
"단체 모임"을 밀어 올릴 이유는 어느 경우에도 없다.

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

CONCENTRATION_AXIS = "concentration"
ENVIRONMENT_AXIS = "environment"
COMPANION_AXIS = "companion"

# 칩 코드 → (축, 그 축에서의 값). 값 어휘는 **발화 쪽과 똑같이 맞춘다**
# (`app.schemas`의 ConcentrationIntent/Environment/Companion) — 이름이 같아야
# 비교가 문자열 하나로 끝나고, 어휘가 갈리면 매핑 표가 하나 더 생긴다.
#
# 코드 단위로 잡는 이유는 place_tag 칩이 코드를 여러 개 들기 때문이다
# ("자연·공원" = 공원·산·호수·계곡·수목원). 칩의 축은 **먼저 걸리는 코드**로 정한다.
# 라벨을 키로 쓰지 않는 것은 문구가 바뀌면 조용히 안 걸리기 때문이다.
#
# **25개 칩 중 13개 코드만 붙였다.** 나머지는 축이 애매해서 일부러 비워 뒀다:
# - 아늑한 공간·힐링하기 좋은·넓고 쾌적한·책 읽기 좋은 — 조용한 쪽으로 기울지만
#   "혼잡도를 말한 칩"은 아니다. 붐비는 아늑한 카페가 모순은 아니다.
# - 카페·전시·문화·시장·쇼핑 — 실내가 많을 뿐 실내외를 말한 칩이 아니다.
#   테라스 카페·전통시장이 야외라서 environment=outdoor와 부딪히지 않는다.
# - 단체 모임(group_gathering) — `Companion` 어휘에 대응 값이 없다. `solo`와는
#   분명히 모순이지만 `friend`·`couple`과는 애매해서, 어느 쪽으로 넣어도 틀리는
#   경우가 생긴다. 재보기 전에는 안 붙인다.
# 넓힐 때는 실측으로 근거를 만든 뒤에 한 줄씩 추가한다.
_CHIP_AXIS_VALUES: dict[str, tuple[str, str]] = {
    # 혼잡도 — concentration_intent
    "quiet": (CONCENTRATION_AXIS, "AVOID"),
    "trendy_hotspot": (CONCENTRATION_AXIS, "SEEK"),
    # 실내외 — environment
    "indoor": (ENVIRONMENT_AXIS, "indoor"),  # "날씨 상관없는 곳"
    "walk": (ENVIRONMENT_AXIS, "outdoor"),  # "산책하기 좋은"
    "공원": (ENVIRONMENT_AXIS, "outdoor"),  # 아래 다섯은 "자연·공원" 한 칩의 코드다
    "산": (ENVIRONMENT_AXIS, "outdoor"),
    "호수": (ENVIRONMENT_AXIS, "outdoor"),
    "계곡": (ENVIRONMENT_AXIS, "outdoor"),
    "수목원": (ENVIRONMENT_AXIS, "outdoor"),
    # 동행 — companion
    "date": (COMPANION_AXIS, "couple"),
    "with_friends": (COMPANION_AXIS, "friend"),
    "with_kids": (COMPANION_AXIS, "child"),
    "with_parents": (COMPANION_AXIS, "parent"),
    "alone": (COMPANION_AXIS, "solo"),
}

# 발화가 그 축을 **정하지 않은** 값들. null과 같이 취급한다.
# - concentration_intent=IGNORE는 "사람 많아도 괜찮아"라 SEEK가 아니다
#   (`prompts/_shared/rules/concentration_intent.md`).
# - environment="any"는 조건을 좁히지 않는 뜻이다(같은 폴더 `environment.md`).
# 둘 다 "상관없다"이므로 칩을 뺄 근거가 못 된다 — 조용한 곳을 저장한 사람에게
# "사람 많아도 괜찮아"는 조용한 곳을 원하지 않는다는 말이 아니다.
_UNDECIDED_CONCENTRATION = frozenset({"IGNORE"})
_UNDECIDED_ENVIRONMENT = frozenset({"any"})


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


def chip_axis_value(chip: SavedPreferenceChip) -> tuple[str, str] | None:
    """칩이 속한 (축, 값). 어느 축도 아니면 `None`이라 절대 빠지지 않는다."""
    for code in chip.codes:
        axis_value = _CHIP_AXIS_VALUES.get(code)
        if axis_value is not None:
            return axis_value
    return None


def spoken_axis_values(
    *,
    concentration_intent: str | None = None,
    environment: str | None = None,
    companion: str | None = None,
) -> dict[str, str]:
    """발화가 값을 확정한 축만 담는다. "상관없다"는 확정으로 치지 않는다."""
    decided: dict[str, str] = {}
    if concentration_intent and concentration_intent not in _UNDECIDED_CONCENTRATION:
        decided[CONCENTRATION_AXIS] = str(concentration_intent)
    if environment and environment not in _UNDECIDED_ENVIRONMENT:
        decided[ENVIRONMENT_AXIS] = str(environment)
    if companion:
        decided[COMPANION_AXIS] = str(companion)
    return decided


def to_taste_query(
    chips: Sequence[SavedPreferenceChip],
    *,
    spoken_taste_query: str | None = None,
    concentration_intent: str | None = None,
    environment: str | None = None,
    companion: str | None = None,
) -> str | None:
    """저장된 칩을 취향 근거 검색 질의로 바꾼다. 쓸 것이 없으면 `None`.

    발화와 겹치거나 부딪히는 칩을 뺀 나머지만 남긴다. **발화 문구는 여기에 넣지
    않는다** — 호출부가 발화 질의 뒤에 이 값을 이어 붙인다
    (`real_recommendation_provider::_taste_matches_for`). 발화 질의는 장소 유형을
    덧붙이는 보강(`_enrich_taste_query`)을 따로 태우기 때문에, 두 문자열을 여기서
    합치면 그 보강이 저장값에까지 걸린다.

    `None`과 빈 문자열을 구분한다. `None`은 "저장값으로 보탤 것이 없다"이고,
    빈 문자열을 돌려주면 호출부가 취향 축을 켜서 전 후보가 0점인 축이 다른 축의
    몫만 깎는다(`scoring.py::_taste_score` 주석).

    라벨을 그대로 쓰고 `codes`는 질의에 넣지 않는다. 코드는 영어라 한국어 임베딩과
    맞지 않는다 — 종로·중구 500곳 실측에서 `healing` 2.6% 대 "힐링하기 좋은" 52.4%,
    `cozy` 13.8% 대 "아늑한 공간" 53.0%였다. 코드는 축을 찾는 데만 쓴다.
    """
    spoken = bool((spoken_taste_query or "").strip())
    decided = spoken_axis_values(
        concentration_intent=concentration_intent,
        environment=environment,
        companion=companion,
    )

    labels: list[str] = []
    for chip in usable_chips(chips):
        axis_value = chip_axis_value(chip)
        if axis_value is not None:
            axis, value = axis_value
            spoken_value = decided.get(axis)
            # 값이 다르면 모순이라 항상 뺀다. 같으면 중복인데, 발화 취향이 있을
            # 때만 뺀다 — 없으면 그 말이 질의 어디에도 안 남는다(모듈 docstring).
            if spoken_value is not None and (spoken_value != value or spoken):
                continue
        labels.append(chip.label.strip())

    if not labels:
        return None
    return " ".join(labels)


__all__ = [
    "COMPANION_AXIS",
    "CONCENTRATION_AXIS",
    "ENVIRONMENT_AXIS",
    "SavedPreferenceChip",
    "chip_axis_value",
    "spoken_axis_values",
    "to_taste_query",
    "usable_chips",
]
