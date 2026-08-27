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
  UserConditions,
} from "../types";
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
  device_location: null,
  device_location_captured_at: null,
  device_location_snoozed_until: null,
  awaiting_clarification: false,
  agentProgress: null,
  streamingIntent: null,
};

type TripAction =
  | { type: "SET_LANGUAGE"; payload: Language }
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
  | { type: "SNOOZE_LOCATION_REFRESH"; payload: { until: number } }
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

function createMessageId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

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
    case "START_CHAT_TURN":
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
        messages: [
          ...state.messages,
          { id: createMessageId("user"), type: "user_text", text: action.payload.userInput },
        ],
        phase: "recommending",
        error: null,
        agentProgress: null,
        streamingIntent: null,
      };
    case "SET_AGENT_PROGRESS":
      return { ...state, agentProgress: action.payload };
    case "APPEND_STREAM_RESULT": {
      const { recommendations, state: streamState, llm_output, elapsedMsClient } = action.payload;
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
          // message_start/message_delta가 답변 말풍선을 먼저 만들고 난 뒤에만 이 이벤트가
          // 온다. 여기서는 카드만 추가해 "카드 → 답변" 역전이 일어나지 않게 한다.
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
      const streamIndex = state.messages.reduce(
        (foundIndex, message, index) =>
          message.type === "assistant_text" && message.streaming ? index : foundIndex,
        -1,
      );
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
      const { response, elapsedMsClient, serverElapsedMs, stageTimings, conditions } = action.payload;
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
      const streamIndex = state.messages.reduce(
        (foundIndex, message, index) =>
          message.type === "assistant_text" && message.streaming ? index : foundIndex,
        -1,
      );
      const streamingMessage = state.messages[streamIndex];
      const streamedMessages =
        streamingMessage?.type === "assistant_text" && streamingMessage.streaming
          ? state.messages.map((message, index) =>
              index === streamIndex
                ? {
                    ...streamingMessage,
                    text:
                      response.message ||
                      (streamingMessage.text === "…"
                        ? state.language === "en"
                          ? "Here are some places that match your preferences."
                          : "이런 곳들을 찾아봤어요:"
                        : streamingMessage.text),
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
      const infoPlaceCard = action.payload.agentResponse.info_place_card ?? null;
      const comparison = action.payload.agentResponse.comparison ?? null;
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
      const clarificationOptions = action.payload.agentResponse.llm_output.clarification?.options;
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
          status: action.payload.status,
          footnote: action.payload.agentResponse.message_footnote ?? undefined,
        });
      }
      if (recommendations) {
        messages.push({
          id: createMessageId("result"),
          type: "recommendation_result",
          recommendations: recommendations.recommendations,
          unverified_recommendations: recommendations.unverified_recommendations,
          travel_origin_toggle: recommendations.travel_origin_toggle,
          elapsed_ms: action.payload.elapsedMsClient,
          server_elapsed_ms: recommendations.elapsed_ms,
        });
      }
      if (schedule) {
        messages.push({
          id: createMessageId("schedule"),
          type: "schedule_result",
          schedule,
          elapsed_ms: action.payload.elapsedMsClient,
        });
      }
      if (infoPlaceCard) {
        messages.push({
          id: createMessageId("info-place"),
          type: "place_info_result",
          card: infoPlaceCard,
        });
      }
      if (comparison) {
        messages.push({
          id: createMessageId("compare"),
          type: "compare_result",
          comparison,
        });
      }
      if (action.payload.agentResponse.state.run_id) {
        messages.push({
          id: createMessageId("feedback"),
          type: "feedback",
          sessionId: action.payload.agentResponse.state.session_id,
          runId: action.payload.agentResponse.state.run_id,
          intent,
          userInput: action.payload.userInput,
          assistantMessage: message,
        });
      }

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
          action.payload.serverElapsedMs ?? recommendations?.elapsed_ms ?? schedule?.elapsed_ms ?? null,
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
          ...state.messages,
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
    case "SNOOZE_LOCATION_REFRESH":
      return { ...state, device_location_snoozed_until: action.payload.until };
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
    () => loadState() ?? initialTripState,
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
