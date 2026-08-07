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

// 실사용 흐름은 /api/chat 한 번으로 해석과 추천을 함께 받는다(AgentResponse).
// llm_output.recommend.conditions가 조건 카드 표시에 쓰이고, recommendations가
// 그대로 결과 메시지가 된다.
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
    if (url.endsWith("/chat")) {
      return Response.json({
        llm_output: interpretResponse,
        state: { session_id: "sess_test", run_id: "run_test" },
        recommendations: { ...recommendationsResponse, elapsed_ms: 12.3 },
        message: "조건에 맞는 장소를 찾아봤어요.",
      });
    }
    return Response.json({ error: { message: "not found" } }, { status: 404 });
  });
}

beforeEach(() => {
  sessionStorage.clear();
  window.history.pushState({}, "", "/");
  vi.stubGlobal("navigator", {
    geolocation: {
      getCurrentPosition: vi.fn((success: PositionCallback) =>
        success({
          coords: { latitude: 37.5788, longitude: 126.977 },
          timestamp: Date.now(),
        } as GeolocationPosition),
      ),
    },
  });
  vi.stubGlobal("fetch", mockFetch());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

test("debug mode shows condition card together with recommendations", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "true");
  render(<App />);

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "비 오는 날 갈 곳",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText(/개발용 입력 해석 결과/)).toBeInTheDocument();
  expect(screen.getByText(/37\.5788,126\.977 · 장소 검색 기준으로 사용/)).toBeInTheDocument();
  expect(screen.getAllByText("비 오는 날 갈 곳").length).toBeGreaterThan(0);
  // Agent가 한 번에 끝내므로 중간 승인 버튼이 없고 추천이 함께 나온다.
  expect(screen.queryByRole("button", { name: "추천 진행" })).not.toBeInTheDocument();
  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  expect(screen.getByText("운영시간 미확인 갤러리")).toBeInTheDocument();
  expect(screen.getByText("운영시간을 확인할 수 없는 장소")).toBeInTheDocument();
});

test("release mode hides debug card and needs only one chat call", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  render(<App />);

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "비 오는 날 갈 곳",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(screen.queryByText(/개발용 입력 해석 결과/)).not.toBeInTheDocument();
  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();

  const fetchMock = vi.mocked(fetch);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(String(fetchMock.mock.calls[0][0])).toContain("/chat");
  const requestBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
  expect(requestBody.device_location).toBe("37.5788,126.977");
});

test("main recommendation requests location permission before opening chat", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  let resolveFetch: ((response: Response) => void) | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    ),
  );
  render(<App />);

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(navigator.geolocation.getCurrentPosition).toHaveBeenCalledTimes(1);
  expect(await screen.findByText("요청 의도와 조건 파악 중")).toBeInTheDocument();
  expect(screen.getByText("기기 위치 확인 완료")).toBeInTheDocument();

  resolveFetch?.(
    Response.json({
      llm_output: interpretResponse,
      state: { session_id: "sess_test", run_id: "run_test", user_conditions: null },
      recommendations: { ...recommendationsResponse, elapsed_ms: 12.3 },
      message: "조건에 맞는 장소를 찾아봤어요.",
    }),
  );
  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
});

test("developer start opens dev chat with audit panel", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  render(<App />);

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "개발자용으로 시작" }));

  expect(await screen.findByText("Agent Runtime Audit")).toBeInTheDocument();
  expect(await screen.findByText(/Intent: RECOMMEND/)).toBeInTheDocument();
  expect(screen.getByText("TripBranch Developer Console")).toBeInTheDocument();
  expect(screen.getAllByText(/비를 피할 실내 장소가 필요해/).length).toBeGreaterThan(1);
});

test("developer audit turn cards remain selectable after multiple turns", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  render(<App />);

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "개발자용으로 시작" }));
  expect(await screen.findByText("Agent Runtime Audit")).toBeInTheDocument();

  await userEvent.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "광화문 근처에서");
  await userEvent.click(screen.getByRole("button", { name: "보내기" }));
  expect(await screen.findByText(/2\. 광화문 근처에서/)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /1\. 비를 피할 실내 장소가 필요해/ }));

  const firstTurnCard = screen.getByRole("button", {
    name: /1\. 비를 피할 실내 장소가 필요해/,
  });
  expect(firstTurnCard.className).toContain("border-emerald-500");
});

test("location permission denial stays on home and shows guidance", async () => {
  vi.stubGlobal("navigator", {
    geolocation: {
      getCurrentPosition: vi.fn((_success: PositionCallback, error: PositionErrorCallback) =>
        error({
          code: 1,
          message: "User denied Geolocation",
          PERMISSION_DENIED: 1,
          POSITION_UNAVAILABLE: 2,
          TIMEOUT: 3,
        }),
      ),
    },
  });
  render(<App />);

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText(/위치 권한이 필요해요/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

test("requesting more places sends a follow-up chat turn with the session id", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  render(<App />);

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "다른 장소 보기" }));

  await waitFor(() => expect(screen.getAllByText("테스트 박물관")).toHaveLength(2));
  const fetchMock = vi.mocked(fetch);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  const requestBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
  // 제외 목록은 B가 단일 기준이라 프론트가 보내지 않는다.
  expect(requestBody.session_id).toBe("sess_test");
  expect(requestBody.user_input).toBe("다른 곳 보여줘");
});

test("clarification turn hints a fuller phrasing in the composer placeholder", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  // 위치를 말하지 않아 Agent가 되묻는 상황: 추천 없이 메시지만 온다.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({
        llm_output: { ...interpretResponse, recommend: null },
        state: { session_id: "sess_test", run_id: "run_test" },
        recommendations: null,
        message: "어디 근처에서 찾아드릴까요? 현재 위치나 원하시는 지역을 알려주세요.",
      }),
    ),
  );
  render(<App />);

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText(/어디 근처에서 찾아드릴까요/)).toBeInTheDocument();
  // 발화를 대신 만들어 보내지 않고, 입력창 안내 문구만 바꾼다.
  expect(screen.getByPlaceholderText("예: 경복궁 근처에서 찾아줘")).toBeInTheDocument();
});

test("chat route redirects without stored state", async () => {
  window.history.pushState({}, "", "/chat");

  render(<App />);

  await waitFor(() => expect(screen.getByText("TripBranch")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
});
