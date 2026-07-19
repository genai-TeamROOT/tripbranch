// tripReducer 단위 테스트: 각 액션(SET_USER_INPUT, SET_INTERPRETED_CONDITIONS,
// UPDATE_INTERPRETED_CONDITIONS, SET_RECOMMENDATIONS, RESET)이 상태를 올바르게
// 바꾸는지, shown_place_ids가 정상적으로 누적되는지 확인한다.

import { describe, expect, it } from "vitest";
import { initialTripState, tripReducer } from "./tripReducer";
import type { InterpretedConditions, RecommendationItem } from "../types/domain";

const conditions: InterpretedConditions = {
  location_query: "경복궁",
  preferred_categories: ["museum", "cafe"],
  weather_condition: "bad",
  search_radius_km: 1.0,
};

const item: RecommendationItem = {
  place_id: "museum_1",
  name: "경복궁 역사 박물관",
  category: "museum",
  distance_km: 0.3,
  remaining_minutes: 120,
  environment_type: "indoor",
  recommendation_reason: "카테고리 적합도 1.00",
  warnings: [],
  total_score: 0.9,
  score_breakdown: { category: 1.0 },
};

describe("tripReducer", () => {
  it("sets user input", () => {
    const state = tripReducer(initialTripState, { type: "SET_USER_INPUT", payload: "hello" });
    expect(state.user_input).toBe("hello");
  });

  it("sets interpreted conditions", () => {
    const state = tripReducer(initialTripState, {
      type: "SET_INTERPRETED_CONDITIONS",
      payload: conditions,
    });
    expect(state.interpreted_conditions).toEqual(conditions);
  });

  it("partially updates interpreted conditions", () => {
    const withConditions = tripReducer(initialTripState, {
      type: "SET_INTERPRETED_CONDITIONS",
      payload: conditions,
    });
    const updated = tripReducer(withConditions, {
      type: "UPDATE_INTERPRETED_CONDITIONS",
      payload: { search_radius_km: 2.0 },
    });
    expect(updated.interpreted_conditions?.search_radius_km).toBe(2.0);
    expect(updated.interpreted_conditions?.location_query).toBe("경복궁");
  });

  it("sets recommendations and accumulates shown_place_ids", () => {
    const state = tripReducer(initialTripState, {
      type: "SET_RECOMMENDATIONS",
      payload: { recommendations: [item], unverified_recommendations: [] },
    });
    expect(state.recommendation_results).toEqual([item]);
    expect(state.shown_place_ids).toEqual(["museum_1"]);
  });

  it("resets to initial state", () => {
    const withInput = tripReducer(initialTripState, { type: "SET_USER_INPUT", payload: "hello" });
    const reset = tripReducer(withInput, { type: "RESET" });
    expect(reset).toEqual(initialTripState);
  });
});
