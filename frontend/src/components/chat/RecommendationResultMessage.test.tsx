import { render, screen } from "@testing-library/react";

import type { RecommendationItem } from "../../types";
import { RecommendationResultMessage } from "./RecommendationResultMessage";

function item(overrides: Partial<RecommendationItem> = {}): RecommendationItem {
  return {
    place_id: "place-1",
    name: "아키비스트 서촌",
    category: "restaurant",
    distance_km: 0.54,
    remaining_minutes: null,
    operating_hours_display: "11:00~21:00",
    environment_type: "indoor",
    recommendation_reason: "테스트 추천이에요.",
    explanations: [],
    warnings: ["지금은 운영시간이 아니에요. 방문 전에 다시 확인해주세요."],
    score: 0.9,
    feature_scores: {},
    weights_used: {},
    ...overrides,
  };
}

function renderResult(unverifiedRecommendations: RecommendationItem[]) {
  render(
    <RecommendationResultMessage
      recommendations={[]}
      unverifiedRecommendations={unverifiedRecommendations}
      elapsedMs={0}
      serverElapsedMs={0}
      isLoading={false}
      onRequestMore={() => {}}
      onRelaxRadius={() => {}}
    />,
  );
}

it("폐점 후보는 운영시간 구간을 숨기지 않고 별도 섹션에 표시한다", () => {
  renderResult([item()]);

  expect(screen.getByText("현재 운영시간이 아닌 장소")).toBeInTheDocument();
  expect(screen.getByText("11:00~21:00 (현재 운영시간 아님)")).toBeInTheDocument();
  expect(screen.queryByText("운영시간을 확인할 수 없는 장소")).not.toBeInTheDocument();
});

it("운영시간 원문도 없는 후보만 확인 불가 섹션에 표시한다", () => {
  renderResult([item({ operating_hours_display: null })]);

  expect(screen.getByText("운영시간을 확인할 수 없는 장소")).toBeInTheDocument();
  expect(screen.getByText("확인 불가")).toBeInTheDocument();
  expect(screen.queryByText("현재 운영시간이 아닌 장소")).not.toBeInTheDocument();
});
