// ResultsPage 테스트: sessionStorage에 미리 채워둔 상태(saveState)로 렌더링해
// 추천 카드와 운영시간 미확인 섹션이 올바르게 표시되는지 확인한다.

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { ResultsPage } from "./ResultsPage";
import { TripProvider } from "../context/TripContext";
import { saveState } from "../context/storage";
import { initialTripState } from "../context/tripReducer";
import type { RecommendationItem } from "../types/domain";

const knownItem: RecommendationItem = {
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

const unverifiedItem: RecommendationItem = {
  ...knownItem,
  place_id: "cafe_2",
  name: "이름 없는 로스터리",
  category: "cafe",
  remaining_minutes: null,
};

function seedState() {
  saveState({
    ...initialTripState,
    interpreted_conditions: {
      location_query: "경복궁",
      preferred_categories: ["museum", "cafe"],
      weather_condition: "bad",
      search_radius_km: 1.0,
    },
    recommendation_results: [knownItem],
    unverified_recommendations: [unverifiedItem],
    shown_place_ids: ["museum_1", "cafe_2"],
  });
}

describe("ResultsPage", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("renders recommendation cards and the unverified section", () => {
    seedState();

    render(
      <TripProvider>
        <MemoryRouter initialEntries={["/results"]}>
          <Routes>
            <Route path="/results" element={<ResultsPage />} />
          </Routes>
        </MemoryRouter>
      </TripProvider>,
    );

    expect(screen.getByText("경복궁 역사 박물관")).toBeInTheDocument();
    expect(screen.getByText("이름 없는 로스터리")).toBeInTheDocument();
    expect(screen.getByText("운영시간을 확인할 수 없는 장소")).toBeInTheDocument();
  });
});
