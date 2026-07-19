// 앱 전역 상태(TripState)와 이를 변경하는 reducer/action 정의.
// user_input, interpreted_conditions, recommendation_results, unverified_recommendations,
// shown_place_ids 다섯 가지를 관리한다(스펙에 명시된 최소 상태 그대로).
// 사용법: 새 액션이 필요하면 TripAction 유니온에 케이스를 추가하고 switch에도 반영할 것 -
// reducer는 항상 순수 함수로 유지(비동기/부수효과는 페이지 컴포넌트에서 처리 후 dispatch만 함).

import type { InterpretedConditions, RecommendationItem } from "../types/domain";

export interface TripState {
  user_input: string;
  interpreted_conditions: InterpretedConditions | null;
  recommendation_results: RecommendationItem[];
  unverified_recommendations: RecommendationItem[];
  shown_place_ids: string[];
}

export const initialTripState: TripState = {
  user_input: "",
  interpreted_conditions: null,
  recommendation_results: [],
  unverified_recommendations: [],
  shown_place_ids: [],
};

export type TripAction =
  | { type: "SET_USER_INPUT"; payload: string }
  | { type: "SET_INTERPRETED_CONDITIONS"; payload: InterpretedConditions }
  | { type: "UPDATE_INTERPRETED_CONDITIONS"; payload: Partial<InterpretedConditions> }
  | {
      type: "SET_RECOMMENDATIONS";
      payload: {
        recommendations: RecommendationItem[];
        unverified_recommendations: RecommendationItem[];
      };
    }
  | { type: "RESET" }
  | { type: "HYDRATE"; payload: TripState };

export function tripReducer(state: TripState, action: TripAction): TripState {
  switch (action.type) {
    case "SET_USER_INPUT":
      return { ...state, user_input: action.payload };

    case "SET_INTERPRETED_CONDITIONS":
      return { ...state, interpreted_conditions: action.payload };

    case "UPDATE_INTERPRETED_CONDITIONS":
      if (!state.interpreted_conditions) return state;
      return {
        ...state,
        interpreted_conditions: { ...state.interpreted_conditions, ...action.payload },
      };

    case "SET_RECOMMENDATIONS": {
      const newIds = action.payload.recommendations.map((item) => item.place_id);
      return {
        ...state,
        recommendation_results: action.payload.recommendations,
        unverified_recommendations: action.payload.unverified_recommendations,
        shown_place_ids: Array.from(new Set([...state.shown_place_ids, ...newIds])),
      };
    }

    case "RESET":
      return initialTripState;

    case "HYDRATE":
      return action.payload;

    default:
      return state;
  }
}
