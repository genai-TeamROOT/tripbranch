"""저장된 취향을 읽어 채점에 넘기는 배선(A 영역) 테스트.

`domain/saved_preference.py`가 **무엇을 질의로 쓸지**를 정하고, 이 배선이
**어디서 읽어 어디로 넘길지**를 맡는다. 순수 함수 테스트만으로는 이 줄이
지워져도 안 잡혀서 따로 못 박는다 — 1.9.0에서 provider 배선 2줄이 그랬다.
"""

from __future__ import annotations

import pytest

from app.auth.principal import Principal
from app.schemas import UserConditions
from app.services.runtime.agent_runtime import _saved_taste_query
from app.state import preferences as state_preferences
from app.state.schema import UserPreference
from app.state.store import InMemoryStateStore

_USER = "user-1"


def _principal() -> Principal:
    return Principal(user_id=_USER, is_anonymous=False)


def _store_with(*items: UserPreference) -> InMemoryStateStore:
    store = InMemoryStateStore()
    state_preferences.replace(store, _USER, list(items))
    return store


def _chip(label: str, source: str, *codes: str) -> UserPreference:
    return UserPreference(label=label, source=source, codes=list(codes))


def test_저장된_취향을_읽어_질의로_만든다() -> None:
    store = _store_with(
        _chip("아늑한 공간", "preference", "cozy"),
        _chip("전망 좋은", "preference", "good_view"),
    )

    assert _saved_taste_query(UserConditions(), _principal(), store) == "아늑한 공간 전망 좋은"


def test_발화에_취향이_있으면_저장소를_읽지_않는다() -> None:
    """조회 자체를 건너뛴다 — D도 None을 주지만 저장소를 안 치는 편이 낫다."""
    store = _store_with(_chip("아늑한 공간", "preference", "cozy"))
    calls: list[str] = []
    original = store.get_preferences
    store.get_preferences = lambda uid: (calls.append(uid), original(uid))[1]  # type: ignore[method-assign]

    result = _saved_taste_query(UserConditions(taste_query="조용한"), _principal(), store)

    assert result is None
    assert calls == []


def test_게스트는_저장할_자리가_없다() -> None:
    """취향은 세션이 아니라 사람에게 붙는 값이라 user_id가 필수다."""
    store = _store_with(_chip("아늑한 공간", "preference", "cozy"))

    assert _saved_taste_query(UserConditions(), None, store) is None


def test_저장소가_없으면_저장값_없이_채점한다() -> None:
    assert _saved_taste_query(UserConditions(), _principal(), None) is None


def test_고른_적이_없으면_None() -> None:
    assert _saved_taste_query(UserConditions(), _principal(), InMemoryStateStore()) is None


def test_칩_종류를_여기서_다시_거르지_않는다() -> None:
    """무엇을 넣을지는 D가 정한다(`domain/saved_preference.py`). 배선은 그대로 따른다.

    양쪽이 각자 거르면 규칙이 갈려서, 화면이 칩을 늘렸을 때 한쪽만 고치고 넘어가게 된다.
    """
    store = _store_with(
        _chip("친구와 함께", "preference", "with_friends"),
        _chip("카페", "place_tag", "카페", "찻집"),
    )

    assert _saved_taste_query(UserConditions(), _principal(), store) == "친구와 함께 카페"


def test_조회가_실패해도_추천을_막지_않는다() -> None:
    """취향은 순위를 다듬는 축이지 후보를 만드는 축이 아니다."""

    class _BrokenStore(InMemoryStateStore):
        def get_preferences(self, user_id: str):  # type: ignore[override]
            raise RuntimeError("저장소 장애")

    assert _saved_taste_query(UserConditions(), _principal(), _BrokenStore()) is None


@pytest.mark.parametrize("spoken", ["", "   "])
def test_공백만_있는_발화는_말하지_않은_것으로_본다(spoken: str) -> None:
    store = _store_with(_chip("아늑한 공간", "preference", "cozy"))

    result = _saved_taste_query(UserConditions(taste_query=spoken), _principal(), store)

    assert result == "아늑한 공간"
