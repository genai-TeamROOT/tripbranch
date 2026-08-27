"""턴이 끝난 뒤 버튼으로 보여줄 다음 발화 후보를 만든다.

역할: 방금 끝난 대화 한 턴(사용자 발화 + 우리 답변 + 이번 턴에 나간 장소들)을 LLM에
      넘겨, 사용자가 이어서 물을 법한 문구 0~3개를 받아 정제한다.
입력: 이 턴의 AgentRequest와 완성된 AgentResponse, LLMProvider.
출력: 버튼에 그대로 넣을 문구 목록. 만들 게 없거나 실패하면 빈 목록.
호출 시점: `run_agent_flow()`가 본체(`_run_agent_flow`)의 응답을 받은 직후 한 번.

**답변을 만드는 LLM 호출에 얹지 않고 별도로 부른다.** 답변 본문을 만드는 경로는
인텐트마다 다르고(GENERAL/INFO/COMPARE만 LLM 자유 생성, RECOMMEND는 카드 wrapper,
SCHEDULE·OUT_OF_SCOPE는 템플릿) 그중 셋은 텍스트를 스트리밍한다 — 같은 호출에서 JSON
필드를 함께 받으려면 스트리밍을 포기해야 한다. 여기서 따로 부르면 SSE 경로에서는 답변이
이미 화면에 다 뜬 뒤에 도는 호출이라 사용자가 기다리는 시간이 늘지 않는다.

실패는 조용히 빈 목록으로 낮춘다. 이 시점의 답변·카드는 이미 확정돼 있어서, 버튼을
못 만든 것 때문에 턴 전체를 실패시킬 이유가 없다.
"""

from __future__ import annotations

import logging

from app.errors import AppError
from app.providers.protocols import LLMProvider
from app.schemas import AgentRequest, AgentResponse, Intent, OutputStatus

logger = logging.getLogger(__name__)

# 버튼은 답변 아래 한 줄에 놓인다. 넷을 넘기면 줄이 접히고 고르는 비용이 답변을 읽는
# 비용보다 커진다.
MAX_SUGGESTIONS = 3

# 모바일 폭에서 한 버튼이 두 줄로 접히지 않는 상한. 프롬프트에도 같은 값을 싣지만
# 지켰는지는 여기서 다시 검사한다.
MAX_LABEL_LENGTH = 30

# 물음표를 떼어낼 문장 끝. **의문문이 될 수 없는 명령형 어미만 넣는다.**
#
# 후속 "질문"이라고 해서 전부 의문문은 아니다 — "이 근처 카페도 추천해줘"는 시키는
# 말이라 물음표가 붙으면 어색하다. 프롬프트에도 규칙을 적었지만 지켰는지는 여기서
# 확인한다.
#
# **일반 규칙으로 넓히지 않는다.** "얼마나 걸려?"나 "주차되나요?"는 물음표가 있어야
# 맞는 문장이고, 무엇이 질문인지를 어미만으로 가르는 규칙은 만들 수 없다. 그래서
# "-줘"처럼 의문문으로 읽힐 여지가 없는 어미만 목록으로 둔다. 목록에 없는 어미가
# 물음표를 달고 오면 그대로 통과하고, 그건 프롬프트 쪽에서 잡을 몫이다.
_IMPERATIVE_ENDINGS = ("줘", "다오", "해봐", "보여줘")

# LLM에 넘길 장소 이름 수. 이번 턴에 화면에 나간 순서대로 앞에서 자른다 — 뒤쪽 카드는
# 사용자가 후속 질문의 대상으로 삼을 확률이 낮은데 토큰만 늘린다.
_MAX_PLACE_NAMES = 5

# 후속 질문을 만들지 않는 Intent.
#
# OUT_OF_SCOPE: 못 하는 요청을 받은 턴이다. 여기서 다음 발화를 권하면 거절 바로 뒤에
#               버튼을 들이미는 모양이 된다.
_SKIPPED_INTENTS = frozenset({Intent.OUT_OF_SCOPE})


def _place_names(response: AgentResponse) -> list[str]:
    """이번 턴에 화면으로 나간 장소 이름을 순서대로 모은다.

    **답변 텍스트만으로는 부족해서 필요하다.** RECOMMEND 성공 경로의 말풍선은
    카드 위에 붙는 고정 문구라(`response_composer._RECOMMEND_WRAPPER_MESSAGE`)
    거기엔 장소 이름이 한 글자도 없다. 이름을 따로 넘기지 않으면 모델은 "다른 곳
    보여줘" 수준의 일반적인 문구밖에 만들지 못한다.
    """

    names: list[str] = []
    recommendations = response.recommendations
    if recommendations is not None:
        names.extend(
            item.name
            for item in [
                *recommendations.recommendations,
                *recommendations.unverified_recommendations,
            ]
        )
    if response.schedule is not None:
        names.extend(item.place_name for item in response.schedule.items)
    if response.comparison is not None:
        names.extend(item.place_name for item in response.comparison.items)
    if response.info_place_card is not None and response.info_place_card.place_name:
        names.append(response.info_place_card.place_name)

    unique: list[str] = []
    for name in names:
        cleaned = name.strip()
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return unique[:_MAX_PLACE_NAMES]


def _should_suggest(response: AgentResponse) -> bool:
    """이 턴에 버튼을 붙일 자리인지 판단한다."""

    if response.llm_output.status is OutputStatus.NEEDS_CLARIFICATION:
        # 서버가 이미 되물은 턴이다. 되묻기 자체가 버튼을 달고 나가기도 해서
        # (ClarificationPayload.options) 두 종류의 버튼이 같은 말풍선에 겹친다.
        return False
    if response.llm_output.intent in _SKIPPED_INTENTS:
        return False
    return bool(response.message.strip())


def _strip_stray_question_mark(label: str) -> str:
    """명령형 문장에 붙은 물음표를 뗀다. 그 밖에는 손대지 않는다."""

    stripped = label.rstrip("?？").rstrip()
    if stripped != label and stripped.endswith(_IMPERATIVE_ENDINGS):
        return stripped
    return label


def _clean(suggestions: list[str], *, user_input: str) -> list[str]:
    """모델이 준 문구를 화면에 올릴 수 있는 형태로 좁힌다.

    프롬프트에 적은 개수·길이 상한은 부탁이고 실제 계약은 여기다. 상한을 넘겨 받아도
    턴을 실패시키지 않고 잘라 쓴다 — 버튼은 답변에 딸린 부가물이라 없는 편이 잘못된
    것보다 낫고, 잘못된 것보다는 몇 개 적은 편이 낫다.
    """

    spoken = user_input.strip()
    cleaned: list[str] = []
    for suggestion in suggestions:
        label = _strip_stray_question_mark(" ".join(suggestion.split()))
        if not label or len(label) > MAX_LABEL_LENGTH:
            continue
        # 방금 한 질문을 그대로 다시 권하지 않는다.
        if label == spoken:
            continue
        if label in cleaned:
            continue
        cleaned.append(label)
        if len(cleaned) == MAX_SUGGESTIONS:
            break
    return cleaned


async def suggest_follow_ups(
    request: AgentRequest, response: AgentResponse, *, llm: LLMProvider
) -> list[str]:
    """이 턴 뒤에 보여줄 후속 질문 문구를 만든다. 실패하면 빈 목록."""

    if not _should_suggest(response):
        return []

    try:
        result = await llm.generate_follow_up_suggestions(
            user_input=request.user_input,
            intent=response.llm_output.intent,
            assistant_message=response.message,
            place_names=_place_names(response),
            max_suggestions=MAX_SUGGESTIONS,
            max_label_length=MAX_LABEL_LENGTH,
        )
    except AppError:
        # Provider 장애(타임아웃·rate limit)는 이 기능에서 흔한 실패다. 스택까지
        # 남기면 정상 운영 중에도 로그가 시끄러워져 메시지만 남긴다.
        logger.warning("후속 질문 제안 실패(답변에는 영향 없음)", exc_info=True)
        return []
    except Exception:
        logger.warning("후속 질문 제안에서 예상 못 한 오류", exc_info=True)
        return []

    return _clean(result.data, user_input=request.user_input)


__all__ = ["MAX_LABEL_LENGTH", "MAX_SUGGESTIONS", "suggest_follow_ups"]
