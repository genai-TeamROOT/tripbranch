/*
 * 역할: TripState sessionStorage 저장/복원 유틸의 회귀 테스트.
 * 입력: 테스트용 TripState fixture와 조작된 sessionStorage 값.
 * 출력: 저장된 JSON, 복원된 상태, 잘못된 값 처리에 대한 assertion.
 * 호출 시점: vitest 실행 시 프론트엔드 상태 persistence 검증에 사용된다.
 * TODO: 상태 migration이 추가되면 과거 버전 fixture 테스트를 넣는다.
 */

import { loadState, saveState } from "./storage";
import type { TripState } from "./TripContext";

const state: TripState = {
  user_input: "비 피할 곳",
  interpreted_conditions: {
    location_query: "경복궁",
    preferred_categories: ["museum", "cafe"],
    weather_condition: "bad",
    search_radius_km: 1,
  },
  recommendations: [],
  unverified_recommendations: [],
  shown_place_ids: [],
  messages: [
    {
      id: "message-1",
      type: "user_text",
      text: "비 피할 곳",
    },
    {
      id: "message-2",
      type: "condition_debug",
      userInput: "비 피할 곳",
      conditions: {
        location_query: "경복궁",
        preferred_categories: ["museum", "cafe"],
        weather_condition: "bad",
        search_radius_km: 1,
      },
      mergedConditions: null,
      status: "pending",
    },
  ],
  phase: "waiting_for_debug_confirmation",
  session_id: "sess_test",
  awaiting_clarification: false,
  error: null,
};

beforeEach(() => {
  sessionStorage.clear();
});

test("saves and restores state", () => {
  saveState(state);

  expect(loadState()).toEqual(state);
});

test("ignores invalid storage", () => {
  sessionStorage.setItem("tripbranch_state", "not json");

  expect(loadState()).toBeNull();
});
