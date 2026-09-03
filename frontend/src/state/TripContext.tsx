/* eslint-disable react-refresh/only-export-components */
/*
 * 역할: 채팅형 여행 추천 흐름의 메시지, 해석 조건, 추천 진행 상태를 보관한다.
 * 입력: 화면 이벤트와 API 응답을 표현한 reducer action.
 * 출력: TripProvider, useTripState, useTripDispatch hook.
 * 호출 시점: App에서 provider로 감싸고 HomePage/ChatPage가 상태를 읽거나 갱신할 때 호출된다.
 * TODO: 실제 세션 저장소나 서버 캐시가 생기면 메시지 persistence 계층을 분리한다.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";
import type {
  ChatSessionDetail,
  PhotoSimilarPlace,
  AgentProgressEvent,
  AgentResponse,
  AgentStageTiming,
  AgentStreamResultEvent,
  ChatMessage,
  ChatPhase,
  DeveloperAuditTurn,
  Intent,
  InterpretedConditions,
  Language,
  LLMOutputStatus,
  RecommendationItem,
  RecommendationsResponse,
  ScheduleResult,
  SessionContextResponse,
  SavedPlaceItem,
  UserConditions,
} from "../types";
import { buildAgentMessages, createMessageId } from "./agentMessages";
import { hasTimeGap } from "./timeSeparator";
import { findStreamingMessageIndex, freezeStreamingMessage } from "./streamingMessage";
import { attachRecommendationsToTurns } from "./pastRecommendations";
import { clearState, loadState, saveState } from "./storage";

export interface TripState {
  /** 사용자 화면 및 API 번역 경계에 적용할 언어. */
  language: Language;
  user_input: string;
  interpreted_conditions: InterpretedConditions | null;
  recommendations: RecommendationItem[];
  unverified_recommendations: RecommendationItem[];
  shown_place_ids: string[];
  messages: ChatMessage[];
  auditTurns: DeveloperAuditTurn[];
  phase: ChatPhase;
  error: string | null;
  /* Agent(B)가 발급한 대화 세션. 후속 발화에서 그대로 돌려보낸다. */
  session_id: string | null;
  /*
   * 마지막 턴이 오간 시각. 다음 발화 위에 시각 구분선을 넣을지 판단하는 데 쓴다.
   *
   * 지난 대화를 열면 그 대화의 마지막 턴 시각이 들어온다 — 몇 시간 뒤에 이어서
   * 물으면 그 발화 위에 지금 시각이 뜬다. 자리를 비웠다가 돌아온 것을 화면이
   * 그대로 보여주는 것이고, 메신저에서 늘 보던 모양이다.
   */
  last_turn_at: string | null;
  /* 최초 추천 시작 시 허용받은 브라우저 위치. 같은 세션의 후속 요청에도 재사용한다. */
  device_location: string | null;
  /** 브라우저에서 device_location을 마지막으로 받아온 시각(ms). */
  device_location_captured_at: number | null;
  /*
   * 사용자가 위치 재확인 질문에서 "이전 위치로 계속"을 눌러 다시 묻지 않기로 미룬
   * 마감 시각(ms). device_location_captured_at과 분리한 이유는
   * utils/locationRefresh.ts 상단 설명 참고 — capturedAt을 갱신하면 GPS를 다시
   * 받지 않았는데도 나이 표시가 리셋되는 문제가 있었다.
   */
  device_location_snoozed_until: number | null;
  /*
   * 직전 턴이 추천 없이 되묻기로 끝났는지. Agent는 "직전에 무엇을 되물었는지"를
   * 다음 턴 Intent 분류에 넘기지 않아서, 사용자가 "경복궁"처럼 짧게 답하면 INFO로
   * 분류돼 추천이 나오지 않는다. 입력창 placeholder로 더 온전한 문장을 유도한다.
   * TODO: Agent가 되묻기 맥락을 이어받게 되면 이 우회는 제거한다.
   */
  awaiting_clarification: boolean;
  /*
   * 사용자가 담은 장소(담은 순서). 서버가 보관하는 상태를 화면이 비추기만 하며,
   * 진실의 원천은 항상 서버다 — 담기/빼기 응답과 세션 조회 결과로만 갱신한다.
   * 순서는 서버가 준 그대로 유지한다. 개수 상한 초과 시 이 순서로 잘리므로
   * 화면에서 정렬을 바꾸면 "왜 그 곳이 빠졌는지" 설명이 어긋난다.
   */
  saved_places: SavedPlaceItem[];
  agentProgress: AgentProgressEvent | null;
  streamingIntent: Intent | null;
}

const initialTripState: TripState = {
  language: "ko",
  user_input: "",
  interpreted_conditions: null,
  recommendations: [],
  unverified_recommendations: [],
  shown_place_ids: [],
  messages: [],
  auditTurns: [],
  phase: "idle",
  error: null,
  session_id: null,
  last_turn_at: null,
  device_location: null,
  device_location_captured_at: null,
  device_location_snoozed_until: null,
  awaiting_clarification: false,
  saved_places: [],
  agentProgress: null,
  streamingIntent: null,
};

type TripAction =
  | { type: "SET_LANGUAGE"; payload: Language }
  | { type: "RESTORE_SESSION"; payload: ChatSessionDetail }
  | { type: "START_INTERPRETING" }
  | { type: "ADD_INTERPRETATION"; payload: InterpretedPayload }
  | { type: "UPDATE_CONDITIONS"; payload: Partial<InterpretedConditions> }
  | { type: "MARK_DEBUG_CONFIRMED" }
  | { type: "START_RECOMMENDATIONS"; payload?: { conditions?: InterpretedConditions } }
  | {
      type: "APPEND_RECOMMENDATIONS";
      payload: RecommendationsResponse & { elapsed_ms_client: number };
    }
  | {
      type: "START_CHAT_TURN";
      payload: {
        userInput: string;
        deviceLocation?: string | null;
        deviceLocationCapturedAt?: number | null;
      };
    }
  | { type: "APPEND_CHAT_TURN"; payload: ChatTurnPayload }
  | { type: "SET_AGENT_PROGRESS"; payload: AgentProgressEvent }
  | { type: "APPEND_STREAM_RESULT"; payload: AgentStreamResultEvent & { elapsedMsClient: number } }
  | { type: "START_STREAM_MESSAGE"; payload: { intent: Intent } }
  | { type: "APPEND_STREAM_MESSAGE_DELTA"; payload: { text: string } }
  | {
      type: "COMPLETE_STREAM_CHAT_TURN";
      payload: {
        response: AgentResponse;
        elapsedMsClient: number;
        serverElapsedMs: number;
        stageTimings: AgentStageTiming[];
        conditions: InterpretedConditions | null;
      };
    }
  /* done 뒤에 도착하는 후속 질문 버튼. 턴은 이미 끝나 있다. */
  | { type: "APPEND_FOLLOW_UP_SUGGESTIONS"; payload: { suggestions: string[] } }
  | {
      type: "APPEND_FAILED_CHAT_TURN";
      payload: {
        userInput: string;
        message: string;
        code: string;
        retryable: boolean;
        details: unknown;
        elapsedMsClient: number;
      };
    }
  /* 로컬 테스트용 "/status" 결과. 대화 상태는 바꾸지 않고 메시지만 덧붙인다. */
  | {
      type: "APPEND_SESSION_STATUS";
      payload: { userInput: string; status: SessionContextResponse | null; error: string | null };
    }
  /* 사진을 고른 즉시. 결과를 기다리는 동안 사진과 "찾는 중"을 먼저 보여준다. */
  | { type: "START_PHOTO_SIMILAR"; payload: { messageId: string; imageUrl: string | null } }
  /* 축소본은 만드는 데 시간이 걸려(createImageBitmap) START_PHOTO_SIMILAR보다
     늦게 완성될 수 있다 — 완성되면 이 액션으로 그 메시지에만 채워 넣는다. */
  | { type: "SET_PHOTO_SIMILAR_IMAGE"; payload: { messageId: string; imageUrl: string } }
  | {
      type: "RESOLVE_PHOTO_SIMILAR";
      payload: {
        messageId: string;
        centerName: string;
        places: PhotoSimilarPlace[];
        candidateCount: number;
        elapsedMs: number;
      };
    }
  /* 검색이 실패했을 때. 사진 말풍선을 남겨두면 영원히 "찾는 중"이 된다. */
  | { type: "FAIL_PHOTO_SIMILAR"; payload: { messageId: string } }
  | { type: "SET_ERROR"; payload: string }
  | { type: "CLEAR_ERROR" }
  | { type: "SET_SAVED_PLACES"; payload: { items: SavedPlaceItem[] } }
  | { type: "SNOOZE_LOCATION_REFRESH"; payload: { until: number } }
  | { type: "SET_DEVICE_LOCATION"; payload: { deviceLocation: string; capturedAt: number } }
  | { type: "CANCEL_CHAT_TURN" }
  | { type: "RESET" };

/* /api/chat 한 번의 응답을 화면 메시지로 옮기기 위한 입력. */
interface ChatTurnPayload {
  userInput: string;
  intent: Intent;
  conditions: InterpretedConditions | null;
  mergedConditions: UserConditions | null;
  message: string;
  recommendations: RecommendationsResponse | null;
  schedule?: ScheduleResult | null;
  sessionId: string | null;
  status: LLMOutputStatus;
  agentResponse: AgentResponse;
  showDebug: boolean;
  elapsedMsClient: number;
  /** SSE progress 이벤트가 있는 응답은 카드 스트림 여부와 무관하게 단계 시간을 보존한다. */
  serverElapsedMs?: number;
  stageTimings?: AgentStageTiming[];
}

interface InterpretedPayload {
  userInput: string;
  conditions: InterpretedConditions;
  showDebug: boolean;
}

/** 지금 타이프라이터가 채우고 있는 assistant_text 메시지의 인덱스. 없으면 -1. */
function buildInterpretationSummary(conditions: InterpretedConditions) {
  const categories =
    conditions.preferred_categories.length > 0
      ? `${conditions.preferred_categories.join(", ")} 중심으로`
      : "조건에 맞춰";
  const weather =
    conditions.weather_condition === "bad"
      ? "비나 날씨 변수를 고려해서"
      : conditions.weather_condition === "good"
        ? "걷기 좋은 날씨를 고려해서"
        : "";
  // 위치를 말하지 않았으면 장소를 지어내지 않는다. 백엔드가 어디서 찾을지 되묻는다.
  const place = conditions.location_query ? `${conditions.location_query} 근처에서 ` : "";
  return `${place}${weather} ${categories} 찾아볼게요.`;
}

function buildInterpretationMessages(payload: InterpretedPayload): ChatMessage[] {
  const userMessage: ChatMessage = {
    id: createMessageId("user"),
    type: "user_text",
    text: payload.userInput,
  };

  if (payload.showDebug) {
    return [
      userMessage,
      {
        id: createMessageId("debug"),
        type: "condition_debug",
        userInput: payload.userInput,
        conditions: payload.conditions,
        mergedConditions: null,
        status: "pending",
      },
    ];
  }

  return [
    userMessage,
    {
      id: createMessageId("summary"),
      type: "interpretation_summary",
      text: buildInterpretationSummary(payload.conditions),
    },
  ];
}

function tripReducer(state: TripState, action: TripAction): TripState {
  switch (action.type) {
    case "SET_LANGUAGE":
      return { ...state, language: action.payload };
    case "START_INTERPRETING":
      return { ...state, phase: "interpreting", error: null };
    case "ADD_INTERPRETATION": {
      const messages = buildInterpretationMessages(action.payload);
      return {
        ...state,
        user_input: action.payload.userInput,
        interpreted_conditions: action.payload.conditions,
        recommendations: [],
        unverified_recommendations: [],
        messages: [...state.messages, ...messages],
        phase: action.payload.showDebug ? "waiting_for_debug_confirmation" : "recommending",
        error: null,
      };
    }
    case "UPDATE_CONDITIONS":
      if (!state.interpreted_conditions) return state;
      return {
        ...state,
        interpreted_conditions: { ...state.interpreted_conditions, ...action.payload },
      };
    case "MARK_DEBUG_CONFIRMED":
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.type === "condition_debug" && message.status === "pending"
            ? { ...message, status: "confirmed" }
            : message,
        ),
      };
    case "START_RECOMMENDATIONS":
      return {
        ...state,
        interpreted_conditions: action.payload?.conditions ?? state.interpreted_conditions,
        phase: "recommending",
        error: null,
      };
    case "APPEND_RECOMMENDATIONS": {
      const shownIds = [
        ...action.payload.recommendations,
        ...action.payload.unverified_recommendations,
      ].map((item) => item.place_id);
      return {
        ...state,
        recommendations: action.payload.recommendations,
        unverified_recommendations: action.payload.unverified_recommendations,
        shown_place_ids: Array.from(new Set([...state.shown_place_ids, ...shownIds])),
        messages: [
          ...state.messages,
          {
            id: createMessageId("result"),
            type: "recommendation_result",
            recommendations: action.payload.recommendations,
            unverified_recommendations: action.payload.unverified_recommendations,
            elapsed_ms: action.payload.elapsed_ms_client,
            server_elapsed_ms: action.payload.elapsed_ms,
          },
        ],
        phase: "ready",
        error: null,
      };
    }
    /*
     * 사이드바 히스토리에서 지난 대화를 불러온다.
     *
     * **session_id를 채운다** — 사이드바가 부르는 것은 조회가 아니라
     * POST /sessions/{id}/resume이고, 그 응답이 온 시점의 세션은 살아 있다.
     * 그래서 이어 물으면 같은 대화에 붙는다(목록에 줄이 하나 더 생기지 않고,
     * 저장된 턴이 그대로 맥락으로 넘어간다).
     *
     * 그래도 resumable을 확인하고 넣는다. 되살리기가 실패해 조회 응답으로
     * 물러난 경우에는 false로 오고, 그때 id를 채우면 화면은 "이어진다"고
     * 말하는데 백엔드는 새 세션을 만드는 상태가 된다.
     *
     * **restore_from_messages면 화면 기록만 쓴다.** 그 안에 그 턴의 AgentResponse가
     * 통째로 들어 있어, 실시간과 같은 buildAgentMessages를 다시 태우면 그때 본
     * 화면이 그대로 나온다. 지연시간만 0으로 넘긴다 — 복원에는 잴 대상이 없다.
     *
     * 아니면 예전 방식으로 되돌린다(말풍선 + 저장된 조각으로 만든 장소 카드).
     * 기록이 없는 옛 대화와, 저장이 한 번 실패해 턴이 빠진 대화가 여기로 온다.
     * 손실이 있지만 통째로 안 보이거나 턴이 조용히 빠진 채로 보이는 것보다 낫다.
     * 온전한지 판정하는 것은 백엔드다 — 같은 계산을 두 군데 두지 않는다.
     */
    case "RESTORE_SESSION": {
      const restored: ChatMessage[] = [];

      /*
       * 언제 오간 대화인지 맨 위에 한 줄로 밝힌다. 예전에는 "지난 대화예요"라는
       * 배너였는데, 메신저의 시각 구분선이 읽지 않아도 뜻이 통하고 화면도 덜
       * 차지한다. 첫 턴의 시각 하나만 둔다 — 턴마다 붙이면 몇 분 간격의 줄이
       * 계속 끼어들어 대화가 끊겨 보인다.
       */
      const startedAt = action.payload.restore_from_messages
        ? action.payload.messages[0]?.recorded_at
        : action.payload.turns[0]?.at;
      if (startedAt) {
        restored.push({
          id: createMessageId("time"),
          type: "time_separator",
          at: startedAt,
          /* 옛 대화는 남은 말풍선으로만 되돌아온다. 앞부분이 없다는 사실을
             배너 대신 이 줄에 붙여 밝힌다. */
          partial: !action.payload.restore_from_messages,
        });
      }

      if (action.payload.restore_from_messages) {
        const lastIndex = action.payload.messages.length - 1;
        action.payload.messages.forEach((record, index) => {
          if (record.user_input) {
            restored.push({
              id: createMessageId("user"),
              type: "user_text",
              text: record.user_input,
            });
          }
          const turn = buildAgentMessages(record.payload, {
            userInput: record.user_input ?? "",
            elapsedMsClient: 0,
          });
          /*
           * 후속 질문 버튼은 마지막 답변에만 남긴다. 실시간에서도 새 발화가
           * 나가는 순간 옛 버튼을 걷어내므로(START_CHAT_TURN), 대화가 끝난
           * 모습은 마지막 턴에만 버튼이 붙어 있는 상태다. 전부 되살리면 지난
           * 답변 기준의 문구를 눌러 지금 맥락과 어긋난 요청이 나간다.
           */
          restored.push(
            ...(index === lastIndex
              ? turn
              : turn.filter((item) => item.type !== "follow_up_suggestions")),
          );
        });
      } else {
        const attached = attachRecommendationsToTurns(
          action.payload.turns,
          action.payload.recommendations,
        );

        action.payload.turns.forEach((turn, index) => {
          restored.push({
            id: createMessageId("user"),
            type: "user_text",
            text: turn.user_input,
          });
          if (turn.assistant_message) {
            restored.push({
              id: createMessageId("assistant"),
              type: "assistant_text",
              text: turn.assistant_message,
            });
          }
          for (const group of attached[index]) {
            restored.push({
              id: createMessageId("past-places"),
              type: "past_recommendation_result",
              places: group,
            });
          }
        });
      }

      return {
        ...initialTripState,
        language: state.language,
        device_location: state.device_location,
        device_location_captured_at: state.device_location_captured_at,
        messages: restored,
        session_id: action.payload.resumable ? action.payload.session_id : null,
        last_turn_at: action.payload.restore_from_messages
          ? (action.payload.messages.at(-1)?.recorded_at ?? null)
          : (action.payload.turns.at(-1)?.at ?? null),
        phase: "idle",
      };
    }
    case "START_CHAT_TURN": {
      const nowIso = new Date().toISOString();
      return {
        ...state,
        user_input: action.payload.userInput,
        device_location: action.payload.deviceLocation ?? state.device_location,
        device_location_captured_at:
          action.payload.deviceLocationCapturedAt ?? state.device_location_captured_at,
        // 진짜 GPS를 새로 받은 턴이면(capturedAt이 실려 왔으면) 미뤄둔 재확인
        // 마감도 함께 해제한다 — 방금 받은 위치가 이미 최신이라 미룰 이유가 없다.
        device_location_snoozed_until:
          action.payload.deviceLocationCapturedAt != null
            ? null
            : state.device_location_snoozed_until,
        // 옛 턴의 후속 질문 버튼은 새 발화가 나가는 순간 걷어낸다. 남겨두면 대화를
        // 위로 올렸을 때 어느 답변에 대한 제안인지 알 수 없고, 지난 답변 기준의
        // 문구를 눌러 지금 맥락과 어긋난 요청이 나간다.
        last_turn_at: nowIso,
        messages: [
          ...freezeStreamingMessage(
            state.messages.filter((message) => message.type !== "follow_up_suggestions"),
          ),
          /* 자리를 비웠다가 돌아와 이어 묻는 발화라면 그 위에 지금 시각을 둔다.
             바로 이어지는 발화에는 넣지 않는다 — 몇 분 간격의 줄이 계속 끼어들면
             대화가 끊겨 보인다. */
          ...(hasTimeGap(state.last_turn_at, nowIso)
            ? [{ id: createMessageId("time"), type: "time_separator" as const, at: nowIso }]
            : []),
          { id: createMessageId("user"), type: "user_text", text: action.payload.userInput },
        ],
        phase: "recommending",
        error: null,
        agentProgress: null,
        streamingIntent: null,
      };
    }
    case "SET_AGENT_PROGRESS":
      return { ...state, agentProgress: action.payload };
    case "APPEND_STREAM_RESULT": {
      const {
        recommendations,
        state: streamState,
        llm_output,
        elapsedMsClient,
        message: wrapperMessage,
      } = action.payload;
      const shownIds = [
        ...recommendations.recommendations,
        ...recommendations.unverified_recommendations,
      ].map((item) => item.place_id);
      return {
        ...state,
        recommendations: recommendations.recommendations,
        unverified_recommendations: recommendations.unverified_recommendations,
        shown_place_ids: Array.from(new Set([...state.shown_place_ids, ...shownIds])),
        session_id: streamState.session_id ?? state.session_id,
        streamingIntent: llm_output.intent,
        messages: [
          ...state.messages,
          // SSE 추천은 고정 안내 → 카드 → LLM 선택 팁 순서다. result에만 담긴
          // 고정 안내를 먼저 넣어, LLM이 길게 생성되는 동안에도 후보를 바로 보여준다.
          ...(wrapperMessage
            ? [
                {
                  id: createMessageId("assistant"),
                  type: "assistant_text" as const,
                  text: wrapperMessage,
                  intent: llm_output.intent,
                  status: llm_output.status,
                },
              ]
            : []),
          {
            id: createMessageId("result"),
            type: "recommendation_result",
            recommendations: recommendations.recommendations,
            unverified_recommendations: recommendations.unverified_recommendations,
            travel_origin_toggle: recommendations.travel_origin_toggle,
            elapsed_ms: elapsedMsClient,
            server_elapsed_ms: recommendations.elapsed_ms,
          },
        ],
      };
    }
    case "START_STREAM_MESSAGE":
      return {
        ...state,
        streamingIntent: action.payload.intent,
        messages: [
          ...state.messages,
          {
            id: createMessageId("assistant-stream"),
            type: "assistant_text",
            text: "…",
            intent: action.payload.intent,
            streaming: true,
          },
        ],
      };
    case "APPEND_STREAM_MESSAGE_DELTA": {
      const streamIndex = findStreamingMessageIndex(state.messages);
      const streamingMessage = state.messages[streamIndex];
      if (streamingMessage?.type === "assistant_text" && streamingMessage.streaming) {
        return {
          ...state,
          messages: state.messages.map((message, index) =>
            index === streamIndex
              ? {
                  ...streamingMessage,
                  // "…"는 빈 말풍선의 로딩 표기일 뿐 실제 답변 본문에 남기지 않는다.
                  text:
                    streamingMessage.text === "…"
                      ? action.payload.text
                      : `${streamingMessage.text}${action.payload.text}`,
                }
              : message,
          ),
        };
      }
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            id: createMessageId("assistant-stream"),
            type: "assistant_text",
            text: action.payload.text,
            intent: state.streamingIntent ?? undefined,
            status: "complete",
            streaming: true,
          },
        ],
      };
    }
    case "COMPLETE_STREAM_CHAT_TURN": {
      const { response, elapsedMsClient, serverElapsedMs, stageTimings, conditions } =
        action.payload;
      const recommendations = response.recommendations;
      const auditTurn: DeveloperAuditTurn = {
        id: createMessageId("audit"),
        userInput: state.user_input,
        intent: response.llm_output.intent,
        status: response.llm_output.status,
        message: response.message,
        sessionId: response.state.session_id,
        runId: response.state.run_id ?? null,
        deviceLocation: state.device_location,
        elapsedMsClient,
        serverElapsedMs,
        stageTimings,
        extractedConditions: conditions,
        beforeConditions: state.auditTurns.at(-1)?.afterConditions ?? null,
        afterConditions: response.state.user_conditions ?? null,
        recommendations,
        response,
        failure: null,
      };
      const streamIndex = findStreamingMessageIndex(state.messages);
      const streamingMessage = state.messages[streamIndex];
      const streamedMessages =
        streamingMessage?.type === "assistant_text" && streamingMessage.streaming
          ? state.messages.map((message, index) =>
              index === streamIndex
                ? {
                    ...streamingMessage,
                    text:
                      streamingMessage.text === "…"
                        ? response.message ||
                          (state.language === "en"
                            ? "Here are some places that match your preferences."
                            : "이런 곳들을 찾아봤어요:")
                        : streamingMessage.text,
                    intent: response.llm_output.intent,
                    status: response.llm_output.status,
                    streaming: false,
                  }
                : message,
            )
          : state.messages;
      const trailingMessages: ChatMessage[] = [];
      if (response.info_place_card !== null && response.info_place_card !== undefined) {
        trailingMessages.push({
          id: createMessageId("place-info"),
          type: "place_info_result",
          card: response.info_place_card,
        });
      }
      if (
        response.secondary_info_place_card !== null &&
        response.secondary_info_place_card !== undefined
      ) {
        // 근처 주차장 → 공영주차장처럼 짝인 실시간 질문의 둘째 카드다(TP-115). 같은
        // 말풍선에 합치지 않고 별도 메시지로 순차 표시해, 답변 아래로 하나씩
        // 쌓이는 기존 카드 흐름과 동일하게 보이게 한다.
        trailingMessages.push({
          id: createMessageId("place-info-secondary"),
          type: "place_info_result",
          card: response.secondary_info_place_card,
        });
      }
      if (response.comparison !== null && response.comparison !== undefined) {
        trailingMessages.push({
          id: createMessageId("compare"),
          type: "compare_result",
          comparison: response.comparison,
        });
      }
      if (response.state.run_id) {
        trailingMessages.push({
          id: createMessageId("feedback"),
          type: "feedback",
          sessionId: response.state.session_id,
          runId: response.state.run_id,
          intent: response.llm_output.intent,
          userInput: state.user_input,
          assistantMessage: response.message,
        });
      }
      if (response.suggested_follow_ups && response.suggested_follow_ups.length > 0) {
        trailingMessages.push({
          id: createMessageId("follow-up"),
          type: "follow_up_suggestions",
          suggestions: response.suggested_follow_ups,
        });
      }
      const messages = [...streamedMessages, ...trailingMessages];
      return {
        ...state,
        interpreted_conditions: conditions ?? state.interpreted_conditions,
        recommendations: recommendations?.recommendations ?? state.recommendations,
        unverified_recommendations:
          recommendations?.unverified_recommendations ?? state.unverified_recommendations,
        session_id: response.state.session_id ?? state.session_id,
        messages,
        auditTurns: [...state.auditTurns, auditTurn],
        awaiting_clarification: false,
        agentProgress: null,
        streamingIntent: null,
        phase: "ready",
        error: null,
      };
    }
    case "APPEND_CHAT_TURN": {
      const { conditions, intent, message, recommendations, schedule, showDebug } = action.payload;
      const messages: ChatMessage[] = [];
      // 옵션 A: 조건 카드는 유지하되 확인 버튼은 없다 — Agent가 해석과 추천을 한 번에
      // 끝내므로 중간에 사용자가 진행을 승인할 지점이 없다.
      if (showDebug && conditions) {
        messages.push({
          id: createMessageId("debug"),
          type: "condition_debug",
          userInput: action.payload.userInput,
          conditions,
          mergedConditions: action.payload.mergedConditions,
          intent,
          status: "confirmed",
        });
      }
      messages.push(
        ...buildAgentMessages(action.payload.agentResponse, {
          userInput: action.payload.userInput,
          elapsedMsClient: action.payload.elapsedMsClient,
        }),
      );

      const shownIds = recommendations
        ? [...recommendations.recommendations, ...recommendations.unverified_recommendations].map(
            (item) => item.place_id,
          )
        : [];
      const auditTurn: DeveloperAuditTurn = {
        id: createMessageId("audit"),
        userInput: action.payload.userInput,
        intent,
        status: action.payload.status,
        message,
        sessionId: action.payload.sessionId,
        runId: action.payload.agentResponse.state.run_id ?? null,
        deviceLocation: state.device_location,
        elapsedMsClient: action.payload.elapsedMsClient,
        serverElapsedMs:
          action.payload.serverElapsedMs ??
          recommendations?.elapsed_ms ??
          schedule?.elapsed_ms ??
          null,
        stageTimings: action.payload.stageTimings ?? [],
        extractedConditions: conditions,
        beforeConditions: state.auditTurns.at(-1)?.afterConditions ?? null,
        afterConditions: action.payload.agentResponse.state.user_conditions ?? null,
        recommendations,
        response: action.payload.agentResponse,
        failure: null,
      };

      return {
        ...state,
        interpreted_conditions: conditions ?? state.interpreted_conditions,
        recommendations: recommendations?.recommendations ?? [],
        unverified_recommendations: recommendations?.unverified_recommendations ?? [],
        // 제외 목록의 단일 기준은 B다. 화면 표시용으로만 누적한다.
        shown_place_ids: Array.from(new Set([...state.shown_place_ids, ...shownIds])),
        session_id: action.payload.sessionId ?? state.session_id,
        // 추천/일정을 기대한 발화인데 결과가 없으면 Agent가 조건을 되물은 것으로 본다.
        awaiting_clarification:
          recommendations === null &&
          !schedule &&
          (intent === "RECOMMEND" || intent === "MODIFY" || intent === "SCHEDULE"),
        messages: [...state.messages, ...messages],
        auditTurns: [...state.auditTurns, auditTurn],
        phase: "ready",
        error: null,
      };
    }
    case "APPEND_FOLLOW_UP_SUGGESTIONS": {
      if (action.payload.suggestions.length === 0) return state;
      return {
        ...state,
        // 이 턴에 이미 붙은 버튼이 있으면 갈아끼운다. 단발 /api/chat 폴백은 응답
        // 안에 문구를 실어 보내므로, 두 경로가 겹쳐 두 벌이 쌓이는 것을 막는다.
        messages: [
          ...state.messages.filter((message) => message.type !== "follow_up_suggestions"),
          {
            id: createMessageId("follow-up"),
            type: "follow_up_suggestions",
            suggestions: action.payload.suggestions,
          },
        ],
      };
    }
    case "APPEND_FAILED_CHAT_TURN": {
      const auditTurn: DeveloperAuditTurn = {
        id: createMessageId("audit-error"),
        userInput: action.payload.userInput,
        intent: "ERROR",
        status: "error",
        message: action.payload.message,
        sessionId: state.session_id,
        runId: null,
        deviceLocation: state.device_location,
        elapsedMsClient: action.payload.elapsedMsClient,
        serverElapsedMs: null,
        stageTimings: [],
        extractedConditions: null,
        beforeConditions: state.auditTurns.at(-1)?.afterConditions ?? null,
        afterConditions: state.auditTurns.at(-1)?.afterConditions ?? null,
        recommendations: null,
        response: null,
        failure: {
          code: action.payload.code,
          message: action.payload.message,
          retryable: action.payload.retryable,
          details: action.payload.details,
        },
      };
      return {
        ...state,
        auditTurns: [...state.auditTurns, auditTurn],
        phase: "error",
        error: action.payload.message,
      };
    }
    case "START_PHOTO_SIMILAR":
      return {
        ...state,
        messages: [
          // 사진 검색도 새 턴이다 — START_CHAT_TURN과 같은 이유로 옛 제안을 걷어낸다.
          ...state.messages.filter((message) => message.type !== "follow_up_suggestions"),
          {
            id: action.payload.messageId,
            type: "photo_similar_result",
            imageUrl: action.payload.imageUrl,
            status: "loading",
            centerName: "",
            places: [],
            candidateCount: 0,
            elapsedMs: 0,
          },
        ],
      };
    case "SET_PHOTO_SIMILAR_IMAGE":
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.id === action.payload.messageId && message.type === "photo_similar_result"
            ? { ...message, imageUrl: action.payload.imageUrl }
            : message,
        ),
      };
    case "RESOLVE_PHOTO_SIMILAR":
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.id === action.payload.messageId && message.type === "photo_similar_result"
            ? {
                ...message,
                status: "done",
                centerName: action.payload.centerName,
                places: action.payload.places,
                candidateCount: action.payload.candidateCount,
                elapsedMs: action.payload.elapsedMs,
              }
            : message,
        ),
      };
    case "FAIL_PHOTO_SIMILAR":
      /* 실패한 사진 말풍선은 지운다. 오류는 배너가 따로 알린다 — 말풍선을
         남기면 무엇이 잘못됐는지 모른 채 사진만 덩그러니 남는다. */
      return {
        ...state,
        messages: state.messages.filter((message) => message.id !== action.payload.messageId),
      };
    case "APPEND_SESSION_STATUS":
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: createMessageId("user"), type: "user_text", text: action.payload.userInput },
          {
            id: createMessageId("status"),
            type: "session_status",
            status: action.payload.status,
            error: action.payload.error,
          },
        ],
      };
    case "SET_ERROR":
      return { ...state, phase: "error", error: action.payload };
    case "CLEAR_ERROR":
      return { ...state, error: null, phase: state.messages.length > 0 ? "ready" : "idle" };
    case "SET_SAVED_PLACES":
      return { ...state, saved_places: action.payload.items };
    case "SNOOZE_LOCATION_REFRESH":
      return { ...state, device_location_snoozed_until: action.payload.until };
    case "SET_DEVICE_LOCATION":
      // 위치 설정 화면에서 "위치 다시 가져오기"를 눌렀을 때. 채팅 턴을 거치지
      // 않고도 다음 요청부터 새 좌표를 쓰도록 미리 갱신해 둔다.
      return {
        ...state,
        device_location: action.payload.deviceLocation,
        device_location_captured_at: action.payload.capturedAt,
        device_location_snoozed_until: null,
      };
    case "CANCEL_CHAT_TURN": {
      // 응답 대기 중 "중단"을 눌렀을 때(§7.2). 아직 생각 중 단계라 타이프라이터
      // 메시지가 없으면(로딩 버블만 있었으면) 아무 것도 안 남기고, 이미 일부
      // 텍스트가 온 상태라면 거기까지만 확정해 얼린다 — 뒤이어 올 카드·후속
      // 질문 이벤트는 연결이 끊겨 더 오지 않으므로 따로 걷어낼 것이 없다.
      const streamIndex = findStreamingMessageIndex(state.messages);
      const streamingMessage = state.messages[streamIndex];
      let messages = state.messages;
      if (streamingMessage?.type === "assistant_text" && streamingMessage.streaming) {
        messages =
          streamingMessage.text === "…"
            ? state.messages.filter((_, index) => index !== streamIndex)
            : state.messages.map((message, index) =>
                index === streamIndex ? { ...streamingMessage, streaming: false } : message,
              );
      }
      return {
        ...state,
        messages,
        phase: messages.length > 0 ? "ready" : "idle",
        agentProgress: null,
        streamingIntent: null,
      };
    }
    case "RESET":
      clearState();
      // 새 대화여도 사용자가 고른 화면 언어는 유지한다.
      return { ...initialTripState, language: state.language };
    default:
      return state;
  }
}

const TripStateContext = createContext<TripState | null>(null);
const TripDispatchContext = createContext<Dispatch<TripAction> | null>(null);

export function TripProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(
    tripReducer,
    initialTripState,
    // 기본값 위에 저장본을 덮는다. 그냥 `loadState() ?? initial`로 두면 새 필드를
    // 추가할 때마다 구버전 저장본에서 그 필드가 undefined로 복원돼, 처음 읽는
    // 쪽에서 터진다(storage.ts가 과거에 겪은 것과 같은 종류의 문제다).
    () => ({ ...initialTripState, ...(loadState() ?? {}) }),
  );
  const value = useMemo(() => state, [state]);

  useEffect(() => {
    saveState(state);
  }, [state]);

  return (
    <TripStateContext.Provider value={value}>
      <TripDispatchContext.Provider value={dispatch}>{children}</TripDispatchContext.Provider>
    </TripStateContext.Provider>
  );
}

export function useTripState() {
  const value = useContext(TripStateContext);
  if (!value) throw new Error("useTripState must be used inside TripProvider");
  return value;
}

export function useTripDispatch() {
  const value = useContext(TripDispatchContext);
  if (!value) throw new Error("useTripDispatch must be used inside TripProvider");
  return value;
}
