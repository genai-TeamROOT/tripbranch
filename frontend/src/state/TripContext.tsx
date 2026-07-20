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
  ChatMessage,
  ChatPhase,
  InterpretedConditions,
  RecommendationItem,
  RecommendationsResponse,
} from "../types";
import { clearState, loadState, saveState } from "./storage";

export interface TripState {
  user_input: string;
  interpreted_conditions: InterpretedConditions | null;
  recommendations: RecommendationItem[];
  unverified_recommendations: RecommendationItem[];
  shown_place_ids: string[];
  messages: ChatMessage[];
  phase: ChatPhase;
  error: string | null;
}

const initialTripState: TripState = {
  user_input: "",
  interpreted_conditions: null,
  recommendations: [],
  unverified_recommendations: [],
  shown_place_ids: [],
  messages: [],
  phase: "idle",
  error: null,
};

type TripAction =
  | { type: "START_INTERPRETING" }
  | { type: "ADD_INTERPRETATION"; payload: InterpretedPayload }
  | { type: "UPDATE_CONDITIONS"; payload: Partial<InterpretedConditions> }
  | { type: "MARK_DEBUG_CONFIRMED" }
  | { type: "START_RECOMMENDATIONS"; payload?: { conditions?: InterpretedConditions } }
  | { type: "APPEND_RECOMMENDATIONS"; payload: RecommendationsResponse }
  | { type: "SET_ERROR"; payload: string }
  | { type: "CLEAR_ERROR" }
  | { type: "RESET" };

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
  return `${conditions.location_query} 근처에서 ${weather} ${categories} 찾아볼게요.`;
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
          },
        ],
        phase: "ready",
        error: null,
      };
    }
    case "SET_ERROR":
      return { ...state, phase: "error", error: action.payload };
    case "CLEAR_ERROR":
      return { ...state, error: null, phase: state.messages.length > 0 ? "ready" : "idle" };
    case "RESET":
      clearState();
      return initialTripState;
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
