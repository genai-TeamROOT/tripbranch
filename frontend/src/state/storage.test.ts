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
