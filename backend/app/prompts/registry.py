"""프롬프트 슬롯 레지스트리 — ``meta.yaml``을 실제로 읽어 버전을 해석한다.

각 인텐트 폴더의 ``meta.yaml``이 슬롯·소유자·현재 관리 버전의 기준이다. 이 모듈은 그
선언을 읽어 (1) 슬롯별 버전 조회와 (2) 한 턴이 실제로 사용한 슬롯들의 버전 문자열
조립을 제공한다.

**왜 필요한가**: 예전에는 실행 기록(B의 LLMOps Trace)에 손으로 적은 고정 문자열
하나(``agent-interpret-prompts-1.0.16``)만 남았다. 담당자가 자기 인텐트의 프롬프트를
고쳐도 그 값이 그대로여서, 나중에 "이 응답은 어느 프롬프트에서 나왔나"에 답할 수
없었다. 이제 인텐트별 슬롯 버전이 기록에 실린다.

의존성: ``meta.yaml`` 파싱에 PyYAML을 쓴다. 프롬프트 본문 로딩(``loader.py``)은 여전히
Markdown만 읽으므로 이 모듈을 import하지 않는 경로는 YAML을 요구하지 않는다.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import yaml

from app.prompts.loader import PROMPT_ROOT, active_variant
from app.schemas import Intent

# 한 턴에 실제로 사용되는 슬롯 목록. 분류(router.classify)는 항상 돌고, 그 뒤 인텐트별
# 추출/편성 슬롯이 하나 더 돈다. 새 인텐트가 생기면 여기에 한 줄을 추가한다.
#
# 답변 생성 슬롯(*.answer, *.summary)은 넣지 않는다 — 기록 시점(step="llm_interpret")에는
# 아직 돌지 않았고, 회귀 판정에 쓰는 지표(intent·조건 추출 정확도)가 전부 해석 단계
# 산출물이라 없이도 추적이 성립한다.
INTENT_SLOTS: dict[Intent, tuple[str, ...]] = {
    Intent.RECOMMEND: ("router.classify", "recommend.extract"),
    Intent.MODIFY: ("router.classify", "modify.extract"),
    Intent.INFO: ("router.classify", "info.extract"),
    Intent.COMPARE: ("router.classify", "compare.extract"),
    Intent.GENERAL: ("router.classify", "general.extract"),
    Intent.SCHEDULE: ("router.classify", "schedule.plan"),
    Intent.OUT_OF_SCOPE: ("router.classify", "out_of_scope.classify"),
}

# LLM 호출 하나(`providers/gemini.py`의 operation)가 어느 슬롯을 쓰는지. 관측에서
# generation 하나에 프롬프트 버전을 붙이는 데 쓴다.
#
# **INTENT_SLOTS와 목적이 다르다.** 저쪽은 "이 턴이 해석 단계에서 어느 슬롯을
# 지났나"(B의 Trace용)라 답변 생성 슬롯을 일부러 뺐다. 이쪽은 **호출 하나가 실제로
# 무엇을 썼나**라서 생성 슬롯(*.answer, *.summary)까지 전부 넣는다 — 그 호출들이
# 토큰과 비용을 가장 많이 쓰는데 버전을 못 달면 비교가 안 된다.
#
# 새 operation을 추가하면서 여기 빠뜨리면 그 호출만 조용히 버전 없이 기록된다.
# tests/test_prompt_operation_slots.py가 gemini.py의 operation 목록과 대조한다.
OPERATION_SLOTS: dict[str, str] = {
    "classify_intent": "router.classify",
    "extract_recommend_conditions": "recommend.extract",
    "extract_modify_conditions": "modify.extract",
    "extract_info_query": "info.extract",
    "extract_compare_request": "compare.extract",
    "extract_general_request": "general.extract",
    "generate_recommendation_summary": "recommend.summary",
    "stream_recommendation_summary": "recommend.summary",
    "generate_compare_summary": "compare.summary",
    "generate_general_answer": "general.answer",
    "stream_general_answer": "general.answer",
    "stream_info_answer": "info.answer",
    "generate_schedule_plan": "schedule.plan",
    "generate_schedule_fill": "schedule.fill",
}

_FALLBACK_SLOTS: tuple[str, ...] = ("router.classify",)
_SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def metadata_paths() -> list[Path]:
    """라이브러리 안의 인텐트별 메타데이터 파일 목록을 반환한다."""

    return sorted(PROMPT_ROOT.glob("*/meta.yaml"))


@cache
def slot_versions() -> dict[str, str]:
    """모든 ``meta.yaml``을 읽어 ``{슬롯 ID: 버전}`` 표를 만든다.

    파일 내용은 프로세스 수명 동안 바뀌지 않는다고 보고 캐시한다(프롬프트 자산도
    같은 전제로 배포 단위로만 바뀐다).
    """

    versions: dict[str, str] = {}
    for path in metadata_paths():
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for slot_id, slot in (document.get("slots") or {}).items():
            version = slot.get("version")
            if not isinstance(version, str) or _SEMVER_PATTERN.fullmatch(version) is None:
                raise ValueError(
                    "프롬프트 슬롯 버전은 MAJOR.MINOR.PATCH 형식이어야 합니다: "
                    f"{path.parent.name}/{slot_id}"
                )
            if slot_id in versions:
                raise ValueError(f"프롬프트 슬롯 ID가 중복됐습니다: {slot_id}")
            versions[slot_id] = version
    return versions


def slots_for(intent: Intent | None) -> tuple[str, ...]:
    """이번 턴이 사용한 슬롯 ID들을 돌려준다. 모르는 인텐트면 분류 슬롯만 남긴다."""

    if intent is None:
        return _FALLBACK_SLOTS
    return INTENT_SLOTS.get(intent, _FALLBACK_SLOTS)


def turn_prompt_version(intent: Intent | None) -> str:
    """실행 기록(Trace)에 남길 프롬프트 버전 문자열을 만든다.

    예: ``router.classify@2.0.0+info.extract@3.0.0``

    과거 기준선으로 실행 중이면(``TRIPBRANCH_PROMPT_VARIANT``) 그 ID를 뒤에 붙여
    "지금 이 기록은 옛 프롬프트로 낸 것"임을 남긴다.

    B는 이 값을 해석하지 않고 문자열로만 저장하므로(llmops-trace-contract-v1.md §7 Q2)
    형식을 바꿔도 B 쪽 스키마 변경이 필요 없다.
    """

    versions = slot_versions()
    rendered = "+".join(
        f"{slot}@{versions[slot]}" for slot in slots_for(intent) if slot in versions
    )
    variant = active_variant()
    if variant != "current":
        return f"{rendered}+variant:{variant}" if rendered else f"variant:{variant}"
    return rendered


def operation_prompt_version(operation: str) -> str | None:
    """LLM 호출 하나에 붙일 프롬프트 버전. 모르는 operation이면 `None`.

    예: `classify_intent` → `router.classify@2.1.0`

    **관측에서 `version` 자리에 넣는 값이다.** `turn_prompt_version()`이 턴 전체를
    한 문자열로 묶는 것과 달리 여기는 호출 하나만 가리킨다 — 한 턴이 슬롯을 여러 개
    쓰므로, 묶어버리면 "`recommend.extract` 2.3.0과 2.4.0 중 어느 쪽이 느린가"를
    가를 수 없다.

    과거 기준선으로 실행 중이면(`TRIPBRANCH_PROMPT_VARIANT`) 그 ID를 뒤에 붙인다 —
    옛 프롬프트로 낸 기록이 현재 버전 통계에 섞이면 비교가 오염된다.
    """

    slot = OPERATION_SLOTS.get(operation)
    if slot is None:
        return None
    version = slot_versions().get(slot)
    if version is None:
        return None
    rendered = f"{slot}@{version}"
    variant = active_variant()
    return rendered if variant == "current" else f"{rendered}+variant:{variant}"
