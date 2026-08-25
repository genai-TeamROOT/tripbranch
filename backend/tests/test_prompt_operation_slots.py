"""LLM 호출 하나가 어느 프롬프트 슬롯을 쓰는지가 빠짐없이 선언돼 있는지 검사한다.

`OPERATION_SLOTS`는 관측(Langfuse)에서 generation 하나에 프롬프트 버전을 붙이는 데
쓴다. 여기 빠진 operation은 **오류 없이 버전만 없는 채로** 기록된다 — 나중에
"`recommend.extract` 2.3.0과 2.4.0 중 어느 쪽이 느린가"를 물을 때 그 호출만 통계에서
조용히 빠진다. 새 operation을 추가하면서 매핑을 빠뜨리는 실수를 여기서 잡는다.

`app/providers/gemini.py`의 `operation=` 리터럴을 소스에서 직접 훑는다. 목록을 손으로
복제하면 그 목록 자체가 낡아서, 검사한다는 사실이 오히려 안심만 준다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.prompts.registry import (
    OPERATION_SLOTS,
    operation_prompt_version,
    slot_versions,
)

_GEMINI_SOURCE = Path(__file__).resolve().parents[1] / "app" / "providers" / "gemini.py"
_OPERATION_LITERAL = re.compile(r'operation="([a-z_]+)"')


def _declared_operations() -> set[str]:
    found = set(_OPERATION_LITERAL.findall(_GEMINI_SOURCE.read_text(encoding="utf-8")))
    assert found, "gemini.py에서 operation 리터럴을 하나도 못 찾았다 — 정규식이 낡았다."
    return found


def test_every_llm_operation_declares_its_prompt_slot() -> None:
    """gemini.py가 부르는 모든 operation이 매핑에 있어야 한다."""
    missing = _declared_operations() - set(OPERATION_SLOTS)

    assert not missing, (
        f"프롬프트 슬롯이 선언되지 않은 operation: {sorted(missing)}. "
        "app/prompts/registry.py의 OPERATION_SLOTS에 추가한다."
    )


def test_mapping_has_no_operations_that_no_longer_exist() -> None:
    """지워진 operation이 매핑에 남아 있으면 매핑을 읽는 사람이 오해한다."""
    stale = set(OPERATION_SLOTS) - _declared_operations()

    assert not stale, f"gemini.py에 없는 operation이 매핑에 남아 있다: {sorted(stale)}"


def test_every_mapped_slot_actually_exists_in_meta_yaml() -> None:
    """오타난 슬롯 ID는 조용히 None을 만든다 — 버전이 안 붙고 끝난다."""
    versions = slot_versions()
    unknown = {slot for slot in OPERATION_SLOTS.values() if slot not in versions}

    assert not unknown, f"meta.yaml에 없는 슬롯 ID: {sorted(unknown)}"


@pytest.mark.parametrize("operation", sorted(OPERATION_SLOTS))
def test_each_operation_resolves_to_a_versioned_slot(operation: str) -> None:
    rendered = operation_prompt_version(operation)

    assert rendered is not None
    assert rendered.startswith(OPERATION_SLOTS[operation] + "@")


def test_unknown_operation_resolves_to_none_instead_of_raising() -> None:
    """관측이 호출부를 죽이면 안 된다 — 모르는 operation은 버전만 없이 지나간다."""
    assert operation_prompt_version("does_not_exist") is None


def test_answer_slots_are_included_unlike_the_trace_side_mapping() -> None:
    """`INTENT_SLOTS`와 목적이 다르다는 걸 고정한다.

    저쪽은 해석 단계 기록용이라 답변 생성 슬롯을 일부러 뺐다. 이쪽은 호출 하나가 실제로
    무엇을 썼나라서 생성 슬롯까지 넣는다 — **그 호출들이 토큰을 가장 많이 쓴다.**
    """
    mapped = set(OPERATION_SLOTS.values())

    assert "recommend.summary" in mapped
    assert "general.answer" in mapped
