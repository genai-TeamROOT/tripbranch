/*
 * 역할: AgentResponse 하나를 화면 말풍선 목록(ChatMessage[])으로 바꾼다.
 * 입력: 한 턴의 AgentResponse와 그 턴에만 있는 값(사용자 발화, 실측 지연).
 * 출력: 그 턴에 화면으로 나갈 메시지들. 순서가 곧 화면 순서다.
 * 호출 시점: 실시간 응답을 받았을 때(TripContext의 APPEND_CHAT_TURN),
 *            지난 대화를 되돌릴 때(RESTORE_SESSION).
 *
 * **이 함수가 한 벌인 것이 요점이다.** 지난 대화를 "그때와 같게" 보이려면
 * 복원 경로가 실시간 경로와 같은 규칙으로 그려야 하는데, 규칙을 두 군데에 두면
 * 한쪽만 고쳐지는 순간 조용히 갈라진다. 백엔드가 AgentResponse를 통째로
 * 보관하는 것(session_messages)도 이 함수를 다시 태우기 위해서다.
 *
 * 조건 디버그 카드와 개발자 Audit은 여기서 만들지 않는다 — 그 둘은 그 턴에
 * 화면으로 나간 것이 아니라 개발자 화면의 부가 정보이고, 복원 대상도 아니다.
 */

import type {
  AgentResponse,
  ChatMessage,
  RecommendationItem,
  TravelOriginToggle,
} from "../types";

export function createMessageId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/*
 * 추천 응답 하나를 화면 메시지 셋으로 편다 — 카드 → 버튼 → 취향 표 순서다.
 *
 * **세 경로가 이 함수를 같이 쓴다**(단발 응답·스트리밍 result·레거시
 * APPEND_RECOMMENDATIONS). 예전에 추천 메시지를 각자 조립하다가 한 곳만 고쳐져
 * 경로에 따라 화면이 갈라진 적이 있어, 조립 규칙을 여기 한 벌만 둔다.
 *
 * 버튼을 따로 떼는 이유는 수명이다 — 다음 발화가 나가면 버튼 메시지만 걷어내고
 * 카드와 표는 기록으로 남긴다(TripContext의 isPastTurnControl).
 */
export function buildRecommendationMessages({
  recommendations,
  unverifiedRecommendations,
  travelOriginToggle,
  elapsedMsClient,
  serverElapsedMs,
}: {
  recommendations: RecommendationItem[];
  unverifiedRecommendations: RecommendationItem[];
  travelOriginToggle?: TravelOriginToggle | null;
  elapsedMsClient: number;
  serverElapsedMs: number;
}): ChatMessage[] {
  const messages: ChatMessage[] = [
    {
      id: createMessageId("result"),
      type: "recommendation_result",
      recommendations,
      unverified_recommendations: unverifiedRecommendations,
      travel_origin_toggle: travelOriginToggle,
      elapsed_ms: elapsedMsClient,
      server_elapsed_ms: serverElapsedMs,
    },
    {
      id: createMessageId("result-actions"),
      type: "recommendation_actions",
      travel_origin_toggle: travelOriginToggle,
      has_no_results: recommendations.length === 0 && unverifiedRecommendations.length === 0,
    },
  ];

  const taggedItems = [...recommendations, ...unverifiedRecommendations].filter(
    (item) => (item.preference_tags?.length ?? 0) > 0,
  );
  // 태그가 하나도 없으면 표가 스스로 null을 반환하므로 빈 메시지를 만들지 않는다.
  if (taggedItems.length > 0) {
    messages.push({
      id: createMessageId("result-tags"),
      type: "preference_tag_summary",
      items: taggedItems.map((item) => ({
        place_id: item.place_id,
        name: item.name,
        preference_tags: item.preference_tags,
      })),
    });
  }

  return messages;
}

interface BuildOptions {
  /** 그 턴의 사용자 발화. 피드백 위젯이 무엇에 대한 평가인지 기록하는 데 쓴다. */
  userInput: string;
  /**
   * 요청부터 응답까지의 클라이언트 실측 시간(ms). 개발자 화면에서만 보인다.
   * 복원에는 잴 대상이 없으므로 0이 넘어온다.
   */
  elapsedMsClient: number;
}

export function buildAgentMessages(
  response: AgentResponse,
  { userInput, elapsedMsClient }: BuildOptions,
): ChatMessage[] {
  const messages: ChatMessage[] = [];
  const intent = response.llm_output.intent;
  const message = response.message;
  const clarificationOptions = response.llm_output.clarification?.options;

  /*
   * **추천 카드가 답변보다 먼저다.** 화면에 실제로 나가는 순서가 그렇다 —
   * 스트리밍 경로는 카드를 담은 result를 먼저 내보내고, 그 아래에 "추천 팁"
   * 말풍선을 연다(agent_runtime의 "화면 순서가 안내 → 카드 → 팁"). 저장된
   * 대화를 되돌릴 때 답변을 위에 놓으면 그때 본 화면과 위아래가 뒤집힌다.
   *
   * 일정·장소정보·비교는 반대다. 그쪽은 스트리밍 result가 없어 답변이 먼저
   * 나가고 카드가 뒤따르므로 아래 순서를 그대로 둔다.
   */
  if (response.recommendations) {
    messages.push(
      ...buildRecommendationMessages({
        recommendations: response.recommendations.recommendations,
        unverifiedRecommendations: response.recommendations.unverified_recommendations,
        travelOriginToggle: response.recommendations.travel_origin_toggle,
        elapsedMsClient,
        serverElapsedMs: response.recommendations.elapsed_ms,
      }),
    );
  }

  if (message && clarificationOptions && clarificationOptions.length > 0) {
    // 인텐트가 모호해 되묻기 버튼이 붙은 턴 — assistant_text 대신 clarification
    // 메시지로 push해서 같은 문구가 두 번 렌더링되지 않게 한다
    // (docs/design/clarification-options.md 6절).
    messages.push({
      id: createMessageId("clarification"),
      type: "clarification",
      text: message,
      options: clarificationOptions,
    });
  } else if (message) {
    messages.push({
      id: createMessageId("assistant"),
      type: "assistant_text",
      text: message,
      intent,
      status: response.llm_output.status,
      footnote: response.message_footnote ?? undefined,
    });
  }

  if (response.schedule) {
    messages.push({
      id: createMessageId("schedule"),
      type: "schedule_result",
      schedule: response.schedule,
      elapsed_ms: elapsedMsClient,
      /* 저장 버튼이 쓴다(SCHEDULE 카드 2). 복원된 대화에서도 payload에 그대로
         들어 있어 지난 일정을 나중에 저장할 수 있다. */
      run_id: response.state?.run_id ?? undefined,
      session_id: response.state?.session_id ?? undefined,
    });
    /* 재편성 버튼은 별도 메시지다 — 다음 발화가 나가면 이것만 걷어내고 일정
       카드는 기록으로 남긴다(recommendation_actions와 같은 규칙). */
    messages.push({
      id: createMessageId("schedule-actions"),
      type: "schedule_actions",
      has_no_schedule: response.schedule.items.length === 0,
    });
  }

  if (response.info_place_card) {
    messages.push({
      id: createMessageId("info-place"),
      type: "place_info_result",
      card: response.info_place_card,
    });
  }

  if (response.secondary_info_place_card) {
    // 근처 주차장 → 공영주차장처럼 짝인 실시간 질문의 둘째 카드다(TP-115).
    messages.push({
      id: createMessageId("info-place-secondary"),
      type: "place_info_result",
      card: response.secondary_info_place_card,
    });
  }

  if (response.comparison) {
    messages.push({
      id: createMessageId("compare"),
      type: "compare_result",
      comparison: response.comparison,
    });
  }

  if (response.state.run_id) {
    messages.push({
      id: createMessageId("feedback"),
      type: "feedback",
      sessionId: response.state.session_id,
      runId: response.state.run_id,
      intent,
      userInput,
      assistantMessage: message,
    });
  }

  if (response.suggested_follow_ups && response.suggested_follow_ups.length > 0) {
    messages.push({
      id: createMessageId("follow-up"),
      type: "follow_up_suggestions",
      suggestions: response.suggested_follow_ups,
    });
  }

  return messages;
}
