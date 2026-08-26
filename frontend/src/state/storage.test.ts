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
  language: "ko",
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
  auditTurns: [],
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
  device_location: "37.5788,126.9770",
  device_location_captured_at: 1_785_000_000_000,
  device_location_snoozed_until: null,
  awaiting_clarification: false,
  agentProgress: null,
  streamingIntent: null,
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

test("restores a session that contains a schedule_result message", () => {
  // isChatMessage()가 schedule_result를 몰라서 이 타입이 하나라도 있으면
  // messages.every(isChatMessage)가 실패해 세션 전체가 버려지던 회귀 테스트.
  const stateWithSchedule: TripState = {
    ...state,
    messages: [
      ...state.messages,
      {
        id: "message-3",
        type: "schedule_result",
        elapsed_ms: 812,
        schedule: {
          items: [],
          total_duration_min: 90,
          route_summary: "경복궁 근처 코스예요.",
          basis_note: "기준 시각 안내",
          elapsed_ms: 45.5,
        },
      },
    ],
  };

  saveState(stateWithSchedule);

  expect(loadState()).toEqual(stateWithSchedule);
});

test("restores a session that contains a place_info_result message", () => {
  const stateWithPlaceInfo: TripState = {
    ...state,
    messages: [
      ...state.messages,
      {
        id: "message-3",
        type: "place_info_result",
        card: {
          question_type: "operating_hours",
          answer_fields: { operating_hours: "09:00~18:00" },
          place_id: "p1",
          place_name: "경복궁",
          latitude: null,
          longitude: null,
          thumbnail_url: null,
          overview: null,
          operating_hours: "09:00~18:00",
          rest_date: null,
          parking: null,
          parking_fee: null,
          fee: null,
          baby_carriage: null,
          pet: null,
          credit_card: null,
          restroom: null,
          homepage: null,
        },
      },
    ],
  };

  saveState(stateWithPlaceInfo);

  expect(loadState()).toEqual(stateWithPlaceInfo);
});

test("restores a session that contains a feedback message", () => {
  // 턴 하나가 끝날 때마다 항상 붙는 좋아요/싫어요 컨트롤 — schedule_result와
  // 같은 이유로 새로고침 시 대화가 통째로 버려지던 회귀 테스트.
  const stateWithFeedback: TripState = {
    ...state,
    messages: [
      ...state.messages,
      {
        id: "message-3",
        type: "feedback",
        sessionId: "sess_test",
        runId: "run_test",
        intent: "RECOMMEND",
        userInput: "비 피할 곳",
        assistantMessage: "근처 카페 3곳을 찾았어요.",
      },
    ],
  };

  saveState(stateWithFeedback);

  expect(loadState()).toEqual(stateWithFeedback);
});

test("restores a session that contains a compare_result message", () => {
  const stateWithCompare: TripState = {
    ...state,
    messages: [
      ...state.messages,
      {
        id: "message-3",
        type: "compare_result",
        comparison: {
          criteria: "time",
          items: [],
        },
      },
    ],
  };

  saveState(stateWithCompare);

  expect(loadState()).toEqual(stateWithCompare);
});

test("restores a session that contains a clarification message", () => {
  const stateWithClarification: TripState = {
    ...state,
    messages: [
      ...state.messages,
      {
        id: "message-3",
        type: "clarification",
        text: "어디 근처에서 찾을까요?",
        options: [{ id: "opt-1", label: "경복궁 근처", resolved_intent: "RECOMMEND" }],
      },
    ],
  };

  saveState(stateWithClarification);

  expect(loadState()).toEqual(stateWithClarification);
});
