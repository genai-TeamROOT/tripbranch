/* eslint-disable react-refresh/only-export-components */
/*
 * 역할: 여행 입력, 해석 조건, 추천 결과를 보관하는 전역 상태 컨텍스트.
 * 입력: reducer action, sessionStorage에 저장된 이전 TripState.
 * 출력: TripProvider, useTripState, useTripDispatch hook.
 * 호출 시점: App에서 provider로 감싸고 각 페이지가 상태를 읽거나 갱신할 때 호출된다.
 * TODO: 상태가 커지면 서버 캐시와 화면 전용 상태를 분리한다.
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
import type { InterpretedConditions, RecommendationItem, RecommendationsResponse } from "../types";
import { clearState, loadState, saveState } from "./storage";

export interface TripState {
  user_input: string;
  interpreted_conditions: InterpretedConditions | null;
  recommendations: RecommendationItem[];
  unverified_recommendations: RecommendationItem[];
  shown_place_ids: string[];
}

const initialTripState: TripState = {
  user_input: "",
  interpreted_conditions: null,
  recommendations: [],
  unverified_recommendations: [],
  shown_place_ids: [],
};

type TripAction =
  | { type: "SET_USER_INPUT"; payload: string }
  | { type: "SET_CONDITIONS"; payload: InterpretedConditions }
  | { type: "UPDATE_CONDITIONS"; payload: Partial<InterpretedConditions> }
  | { type: "SET_RECOMMENDATIONS"; payload: RecommendationsResponse }
  | { type: "RESET" };

function tripReducer(state: TripState, action: TripAction): TripState {
  switch (action.type) {
    case "SET_USER_INPUT":
      return { ...state, user_input: action.payload };
    case "SET_CONDITIONS":
      return { ...state, interpreted_conditions: action.payload };
    case "UPDATE_CONDITIONS":
      if (!state.interpreted_conditions) return state;
      return {
        ...state,
        interpreted_conditions: { ...state.interpreted_conditions, ...action.payload },
      };
    case "SET_RECOMMENDATIONS": {
      const shownIds = [
        ...action.payload.recommendations,
        ...action.payload.unverified_recommendations,
      ].map((item) => item.place_id);
      return {
        ...state,
        recommendations: action.payload.recommendations,
        unverified_recommendations: action.payload.unverified_recommendations,
        shown_place_ids: Array.from(new Set([...state.shown_place_ids, ...shownIds])),
      };
    }
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
