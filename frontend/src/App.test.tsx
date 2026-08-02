/*
 * 역할: 채팅형 사용자 흐름과 보호 라우팅을 검증하는 앱 통합 테스트.
 * 입력: mocked fetch 응답, feature flag 환경변수, 브라우저 상호작용.
 * 출력: 모드별 메시지 렌더링과 API 호출에 대한 assertion.
 * 호출 시점: vitest 실행 시 프론트엔드 smoke/regression 테스트로 호출된다.
 * TODO: 실제 다회 대화 의미 분석이 생기면 후속 입력 시나리오를 확장한다.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

// /api/interpret은 LLMOutput을 state와 함께 감싼 InterpretResponse({ output, state })를
// 반환한다. interpretUserInput()이 output을 벗겨 RECOMMEND 결과를
// 옛 InterpretedConditions 형태로 변환하므로, 아래 값들이
// location_query="경복궁"/preferred_categories=["museum","cafe"]/weather_condition="bad"로
// 변환되어야 기존 화면 검증이 그대로 통과한다.
const interpretResponse = {
  intent: "RECOMMEND",
  status: "complete",
  recommend: {
    conditions: {
      current_location: null,
      search_center: "경복궁",
      place_types: [],
      place_tags: ["museum", "cafe"],
      weather: "rain",
      weather_intent: "AVOID",
      transport: null,
      max_travel_time: null,
      time_available: null,
      environment: "indoor",
      companion: null,
      budget: null,
      exclude_tags: [],
      special_requirements: [],
    },
  },
  info: null,
  modify: null,
  compare: null,
  general: null,
  out_of_scope: null,
  clarification: null,
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

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/interpret")) {
      return Response.json({ output: interpretResponse, state: {} });
    }
    if (url.endsWith("/recommendations")) {
      return Response.json(recommendationsResponse);
    }
    return Response.json({ error: { message: "not found" } }, { status: 404 });
  });
}

beforeEach(() => {
  sessionStorage.clear();
  window.history.pushState({}, "", "/");
  vi.stubGlobal("fetch", mockFetch());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

test("debug mode shows condition debug message before recommendations", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "true");
  render(<App />);

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "비 오는 날 갈 곳",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText("개발용 입력 해석 결과")).toBeInTheDocument();
  expect(screen.getAllByText("비 오는 날 갈 곳").length).toBeGreaterThan(0);
  expect(screen.queryByText("테스트 박물관")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "추천 진행" }));

  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  expect(screen.getByText("운영시간 미확인 갤러리")).toBeInTheDocument();
  expect(screen.getByText("운영시간을 확인할 수 없는 장소")).toBeInTheDocument();
});

test("release mode hides debug message and requests recommendations automatically", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  render(<App />);

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "비 오는 날 갈 곳",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText(/경복궁 근처에서/)).toBeInTheDocument();
  expect(screen.queryByText("개발용 입력 해석 결과")).not.toBeInTheDocument();
  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();

  const fetchMock = vi.mocked(fetch);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(String(fetchMock.mock.calls[0][0])).toContain("/interpret");
  expect(String(fetchMock.mock.calls[1][0])).toContain("/recommendations");
});

test("requesting more places appends a new result message with shown ids", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  render(<App />);

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "다른 장소 보기" }));

  await waitFor(() => expect(screen.getAllByText("테스트 박물관")).toHaveLength(2));
  const fetchMock = vi.mocked(fetch);
  const requestBody = JSON.parse(String(fetchMock.mock.calls[2][1]?.body));
  expect(requestBody.shown_place_ids).toEqual(["stub-museum-1", "stub-gallery-1"]);
});

test("chat route redirects without stored state", async () => {
  window.history.pushState({}, "", "/chat");

  render(<App />);

  await waitFor(() => expect(screen.getByText("TripBranch")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
});
