import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { TripProvider } from "../../state/TripContext";
import type { RecommendationItem, TravelOriginToggle } from "../../types";
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
    taste_evidence: [],
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
    { wrapper: TripProvider },
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

it("장소별 취향 태그와 문서 단위 언급 수를 표로 표시한다", () => {
  renderResult([
    item({
      preference_tags: [
        { code: "quiet", label: "조용히 머물기 좋은", mention_count: 7 },
        { code: "date", label: "데이트하기 좋은", mention_count: 4 },
        { code: "walk", label: "산책하기 좋은", mention_count: 3 },
        { code: "nature", label: "자연을 즐기기 좋은", mention_count: 2 },
      ],
    }),
  ]);

  const table = screen.getByRole("table", { name: "장소별 방문자 취향 태그" });
  expect(
    screen.getByText("네이버 블로그 후기와 구글 지도 리뷰 약 30건에서 언급된 태그입니다."),
  ).toBeInTheDocument();
  expect(within(table).getByText("아키비스트 서촌")).toBeInTheDocument();
  expect(within(table).getByText("조용히 머물기 좋은 (7)")).toBeInTheDocument();
  expect(within(table).getByText("데이트하기 좋은 (4)")).toBeInTheDocument();
  expect(within(table).getByText("산책하기 좋은 (3)")).toBeInTheDocument();
  expect(within(table).queryByText("자연을 즐기기 좋은 (2)")).not.toBeInTheDocument();
});

it("추천 카드를 클릭하면 C PlaceDetails가 채워진 상세 창을 연다", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      status: "success",
      requested_place_id: "place-1",
      place_card: {
        question_type: "general_info",
        answer_fields: { homepage: "https://example.test/archivist" },
        place_id: "place-1",
        place_name: "아키비스트 서촌",
        thumbnail_url: "https://example.test/archivist.jpg",
        overview: "서촌의 카페입니다.",
        operating_hours: "11:00~21:00",
        rest_date: "매주 화요일",
        parking: null,
        parking_fee: null,
        fee: null,
        baby_carriage: null,
        pet: null,
        credit_card: "가능",
        restroom: null,
        homepage: "https://example.test/archivist",
      },
    }),
  });
  vi.stubGlobal("fetch", fetchMock);
  window.fetch = fetchMock;
  render(
    <RecommendationResultMessage
      recommendations={[item()]}
      unverifiedRecommendations={[]}
      elapsedMs={0}
      serverElapsedMs={0}
      isLoading={false}
      onRequestMore={() => {}}
      onRelaxRadius={() => {}}
    />,
    { wrapper: TripProvider },
  );

  await user.click(screen.getByRole("button", { name: "아키비스트 서촌 장소 정보 미리 보기" }));

  const dialog = screen.getByRole("dialog", { name: "아키비스트 서촌" });
  expect(dialog).toBeInTheDocument();
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith("/api/chat/place-details", expect.anything()),
  );
  expect(
    await within(dialog).findByRole("img", { name: "아키비스트 서촌 이미지" }),
  ).toBeInTheDocument();
  expect(within(dialog).getByText("서촌의 카페입니다.")).toBeInTheDocument();
  expect(within(dialog).getByText("매주 화요일")).toBeInTheDocument();
  expect(within(dialog).getByText("11:00~21:00 (현재 운영시간 아님)")).toBeInTheDocument();
  // 홈페이지는 "관련 정보" 박스 안에서 클릭 가능한 링크로만 노출된다(하단 중복 링크 제거).
  expect(
    within(dialog).getByRole("link", { name: "https://example.test/archivist" }),
  ).toHaveAttribute("href", "https://example.test/archivist");

  await user.click(screen.getByRole("button", { name: "상세 창 닫기" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- 비차단형 전환 버튼(TravelOriginToggle, D-071) ---------------------------

function toggle(overrides: Partial<TravelOriginToggle> = {}): TravelOriginToggle {
  return {
    alternative_origin: "search_center",
    alternative_origin_name: "안국역",
    ...overrides,
  };
}

it("travelOriginToggle이 없으면 전환 버튼을 렌더링하지 않는다", () => {
  render(
    <RecommendationResultMessage
      recommendations={[item()]}
      unverifiedRecommendations={[]}
      elapsedMs={0}
      serverElapsedMs={0}
      isLoading={false}
      onRequestMore={() => {}}
      onRelaxRadius={() => {}}
    />,
    { wrapper: TripProvider },
  );

  expect(screen.queryByText(/기준으로 다시 보기/)).not.toBeInTheDocument();
});

it("travelOriginToggle이 있으면 대상 이름을 딴 전환 버튼을 렌더링하고 클릭 시 그대로 넘긴다", async () => {
  const user = userEvent.setup();
  const onToggleTravelOrigin = vi.fn();
  render(
    <RecommendationResultMessage
      recommendations={[item()]}
      unverifiedRecommendations={[]}
      travelOriginToggle={toggle()}
      elapsedMs={0}
      serverElapsedMs={0}
      isLoading={false}
      onRequestMore={() => {}}
      onRelaxRadius={() => {}}
      onToggleTravelOrigin={onToggleTravelOrigin}
    />,
    { wrapper: TripProvider },
  );

  const button = screen.getByRole("button", { name: "안국역 기준으로 다시 보기" });
  await user.click(button);

  expect(onToggleTravelOrigin).toHaveBeenCalledWith(toggle());
});

it("영어 화면에서는 추천 카드의 고정 문구와 전환 버튼을 영어로 표시한다", () => {
  render(
    <RecommendationResultMessage
      recommendations={[
        item({
          remaining_minutes: 120,
          recommendation_reason: "날씨·운영시간·거리 조건을 종합한 1순위 추천이에요.",
        }),
      ]}
      unverifiedRecommendations={[]}
      travelOriginToggle={toggle({ alternative_origin_name: "Myeongdong" })}
      elapsedMs={0}
      serverElapsedMs={0}
      isLoading={false}
      onRequestMore={() => {}}
      onRelaxRadius={() => {}}
      onToggleTravelOrigin={() => {}}
      language="en"
    />,
    { wrapper: TripProvider },
  );

  expect(screen.getByText("Here are some places that match your preferences.")).toBeInTheDocument();
  expect(screen.getByText("Recommended places")).toBeInTheDocument();
  expect(
    screen.getByText("Recommended #1 based on weather, opening hours, and distance."),
  ).toBeInTheDocument();
  expect(screen.getByText("Preview")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Show more places" })).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "View results based on Myeongdong" }),
  ).toBeInTheDocument();
});

it("결과가 0건이어도 travelOriginToggle이 있으면 반경 확대 버튼과 함께 전환 버튼을 보여준다", () => {
  render(
    <RecommendationResultMessage
      recommendations={[]}
      unverifiedRecommendations={[]}
      travelOriginToggle={toggle({ alternative_origin_name: "혜화역" })}
      elapsedMs={0}
      serverElapsedMs={0}
      isLoading={false}
      onRequestMore={() => {}}
      onRelaxRadius={() => {}}
      onToggleTravelOrigin={() => {}}
    />,
    { wrapper: TripProvider },
  );

  expect(screen.getByText("조건에 맞는 장소를 찾지 못했어요.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "혜화역 기준으로 다시 보기" })).toBeInTheDocument();
});
