/* COMPARE(TRAVEL_TIME) 카드가 장소별 거리·수단별 소요시간과 최단 수단 배지를 보여주는지 검증한다. */

import { render, screen } from "@testing-library/react";
import type { ComparisonItem, ComparisonResult } from "../../types";
import { CompareResultCards } from "./CompareResultCards";

function makeItem(overrides: Partial<ComparisonItem>): ComparisonItem {
  return {
    place_id: "1",
    place_name: "장소",
    rank: 1,
    distance_km: null,
    remaining_minutes: null,
    environment_type: null,
    latitude: null,
    longitude: null,
    travel_distance_km: null,
    travel_walking_minutes: null,
    travel_driving_minutes: null,
    travel_transit_minutes: null,
    ...overrides,
  };
}

it("travel_time 기준이면 장소별 거리·수단별 소요시간 카드를 보여주고, 가장 빠른 곳에 배지를 단다", () => {
  const comparison: ComparisonResult = {
    criteria: "travel_time",
    items: [
      makeItem({
        place_id: "a",
        place_name: "서울공예박물관",
        travel_distance_km: 1.92,
        travel_walking_minutes: 12,
        travel_driving_minutes: 10,
        travel_transit_minutes: 2,
      }),
      makeItem({
        place_id: "b",
        place_name: "가회민화박물관",
        travel_distance_km: 1.97,
        travel_walking_minutes: 21,
        travel_driving_minutes: 11,
        travel_transit_minutes: 3,
      }),
    ],
  };

  render(<CompareResultCards comparison={comparison} />);

  expect(screen.getByText("서울공예박물관")).toBeInTheDocument();
  expect(screen.getByText("가회민화박물관")).toBeInTheDocument();
  expect(screen.getByText("약 1.92km")).toBeInTheDocument();
  expect(screen.getAllByText("2분")).toHaveLength(1);
  expect(screen.getByText("가장 빠름")).toBeInTheDocument();
});

it("travel_time이 아니면 아무것도 렌더링하지 않는다", () => {
  const comparison: ComparisonResult = {
    criteria: "overall",
    items: [makeItem({ place_id: "a", place_name: "장소 A" })],
  };

  const { container } = render(<CompareResultCards comparison={comparison} />);
  expect(container).toBeEmptyDOMElement();
});

it("이동 경로를 확인하지 못한 장소는 안내 문구만 보여준다", () => {
  const comparison: ComparisonResult = {
    criteria: "travel_time",
    items: [makeItem({ place_id: "a", place_name: "장소 A" })],
  };

  render(<CompareResultCards comparison={comparison} />);
  expect(screen.getByText("이동 경로를 확인하지 못했어요.")).toBeInTheDocument();
});
