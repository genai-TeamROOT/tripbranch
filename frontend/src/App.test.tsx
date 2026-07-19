/*
 * 역할: 주요 사용자 흐름과 보호 라우팅을 검증하는 앱 통합 테스트.
 * 입력: mocked fetch 응답, MemoryRouter 수준의 브라우저 상호작용.
 * 출력: 화면 전환, API 호출, 결과 렌더링에 대한 assertion.
 * 호출 시점: vitest 실행 시 프론트엔드 smoke/regression 테스트로 호출된다.
 * TODO: 오류 배너와 재추천 흐름이 생기면 사용자 시나리오를 확장한다.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

const interpretResponse = {
  location_query: "경복궁",
  preferred_categories: ["museum", "cafe"],
  weather_condition: "bad",
  search_radius_km: 1.0,
};

const recommendationsResponse = {
  recommendations: [
    {
      place_id: "stub-museum-1",
      name: "테스트 박물관",
      category: "museum",
      distance_km: 0.4,
      remaining_minutes: 150,
      environment_type: "indoor",
      recommendation_reason: "비 오는 날 방문하기 좋은 실내 장소예요.",
      warnings: [],
    },
  ],
  unverified_recommendations: [
    {
      place_id: "stub-gallery-1",
      name: "운영시간 미확인 갤러리",
      category: "gallery",
      distance_km: 0.8,
      remaining_minutes: null,
      environment_type: "indoor",
      recommendation_reason: "선호한 문화 장소와 비슷한 장소예요.",
      warnings: ["방문 전에 운영 여부를 확인해주세요."],
    },
  ],
};

beforeEach(() => {
  sessionStorage.clear();
  window.history.pushState({}, "", "/");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/interpret")) {
        return Response.json(interpretResponse);
      }
      if (url.endsWith("/recommendations")) {
        return Response.json(recommendationsResponse);
      }
      return Response.json({ error: { message: "not found" } }, { status: 404 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("input to confirm to results flow shows recommendations", async () => {
  render(<App />);

  await userEvent.type(screen.getByPlaceholderText(/경복궁 근처/), "비 오는 날 갈 곳");
  await userEvent.click(screen.getByRole("button", { name: "조건 확인하기" }));

  expect(await screen.findByText("조건 확인")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "추천 받기" }));

  expect(await screen.findByText("추천 결과")).toBeInTheDocument();
  expect(screen.getByText("테스트 박물관")).toBeInTheDocument();
  expect(screen.getByText("운영시간 미확인 갤러리")).toBeInTheDocument();
  expect(screen.getByText("운영시간을 확인할 수 없는 장소")).toBeInTheDocument();
});

test("protected results route redirects without stored state", async () => {
  window.history.pushState({}, "", "/results");

  render(<App />);

  await waitFor(() => expect(screen.getByText("TripBranch")).toBeInTheDocument());
});
