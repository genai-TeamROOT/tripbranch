/*
 * 역할: 채팅형 사용자 흐름과 보호 라우팅을 검증하는 앱 통합 테스트.
 * 입력: mocked fetch 응답, feature flag 환경변수, 브라우저 상호작용.
 * 출력: 모드별 메시지 렌더링과 API 호출에 대한 assertion.
 * 호출 시점: vitest 실행 시 프론트엔드 smoke/regression 테스트로 호출된다.
 * TODO: 실제 다회 대화 의미 분석이 생기면 후속 입력 시나리오를 확장한다.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

function chatResponse() {
  return {
    llm_output: interpretResponse,
    state: { session_id: "sess_test", run_id: "run_test", user_conditions: null },
    recommendations: { ...recommendationsResponse, elapsed_ms: 12.3 },
    message: "조건에 맞는 장소를 찾아봤어요.",
    suggested_follow_ups: ["테스트 박물관 운영시간 알려줘", "다른 곳도 보여줘"],
  };
}

function streamResponse(
  response: {
    llm_output: { intent: string; [key: string]: unknown };
    state: unknown;
    recommendations: unknown;
    message: string;
    message_footnote?: string;
    suggested_follow_ups?: string[];
  } = chatResponse(),
) {
  const events: Array<{ event: string; data: unknown }> = [
    {
      event: "progress",
      data: { stage: "interpreting", message: "조건을 파악하고 있어요.", elapsed_ms: 1 },
    },
  ];
  if (response.recommendations) {
    events.push(
      {
        event: "result",
        data: {
          llm_output: response.llm_output,
          state: response.state,
          recommendations: response.recommendations,
          message: "이런 곳들을 찾아봤어요:",
          elapsed_ms: 2,
        },
      },
      {
        event: "message_start",
        data: { intent: response.llm_output.intent, elapsed_ms: 3 },
      },
      { event: "message_delta", data: { text: response.message, elapsed_ms: 4 } },
    );
  }
  // 실제 서버와 같은 순서를 흉내 낸다 — 후속 질문은 done **뒤에** 별도 이벤트로
  // 온다(D-102). done 응답 자체에는 담기지 않는다.
  const { suggested_follow_ups: followUps, ...doneResponse } = response;
  events.push({ event: "done", data: { response: doneResponse, elapsed_ms: 5 } });
  if (followUps && followUps.length > 0) {
    events.push({ event: "follow_ups", data: { suggestions: followUps, elapsed_ms: 6 } });
  }
  const payload = events
    .map(({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(payload));
      controller.close();
    },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
}

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/chat/stream")) return streamResponse();
    if (url.endsWith("/chat")) {
      return Response.json(chatResponse());
    }
    return Response.json({ error: { message: "not found" } }, { status: 404 });
  });
}

beforeEach(() => {
  sessionStorage.clear();
  window.history.pushState({}, "", "/");
  // 로컬 .env의 Codex 테스트 좌표가 브라우저 권한 회귀 테스트에 영향을 주지 않게 한다.
  vi.stubEnv("VITE_TEST_DEVICE_LOCATION", "");
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

/* 게스트 세션 확인이 끝나 관문(RequireUser)을 통과할 때까지 기다린다(D-062).
   렌더 직후에는 세션 조회가 아직 진행 중이라 홈 화면이 그려지지 않은 상태다. */
async function renderApp() {
  render(<App />);
  await screen.findByRole("button", { name: "추천 시작하기" });
}

test("user chat hides condition debug card and shows recommendations", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "true");
  await renderApp();

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "비 오는 날 갈 곳",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(screen.queryByText(/개발용 입력 해석 결과/)).not.toBeInTheDocument();
  // 홈 컴포저가 ChatComposer와 공유되면서(HomePage/ChatComposer 통합) 제출이
  // "칩으로 채우기 → 컴포저가 자기 state를 비우고 → 위치 조회 1틱을 더 거쳐"
  // /chat으로 넘어가므로, 클릭 직후 동기 조회 대신 비동기로 기다린다.
  expect((await screen.findAllByText("비 오는 날 갈 곳")).length).toBeGreaterThan(0);
  // Agent가 한 번에 끝내므로 중간 승인 버튼이 없고 추천이 함께 나온다.
  expect(screen.queryByRole("button", { name: "추천 진행" })).not.toBeInTheDocument();
  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  // 신원 표시는 사이드바에 상시 떠 있다(D-062) — 채팅 화면에서도 사이드바를 통해
  // 이어진다. 데스크톱 사이드바(role=complementary)로 좁혀서 찾는다(모바일
  // 드로어도 같은 SideDrawerContent를 렌더해 텍스트가 중복된다).
  expect(
    within(screen.getByRole("complementary")).getByText("게스트로 이용 중"),
  ).toBeInTheDocument();
  expect(screen.getByText("운영시간 미확인 갤러리")).toBeInTheDocument();
  expect(screen.getByText("운영시간을 확인할 수 없는 장소")).toBeInTheDocument();
});

test("streamed recommendation renders template, cards, then the LLM tip", async () => {
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  const template = await screen.findByText("이런 곳들을 찾아봤어요:");
  const firstCard = screen.getByText("테스트 박물관");
  const tip = await screen.findByText("조건에 맞는 장소를 찾아봤어요.");
  expect(template.compareDocumentPosition(firstCard) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(
    0,
  );
  expect(firstCard.compareDocumentPosition(tip) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
});

test("user chat needs only one chat call", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  await renderApp();

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

test("asks whether to refresh a location older than 30 minutes before a follow-up", async () => {
  const now = vi.spyOn(Date, "now");
  now.mockReturnValue(1_000);
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await screen.findByText("테스트 박물관");

  now.mockReturnValue(30 * 60 * 1000 + 1_001);
  await userEvent.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "다른 곳 보여줘");
  await userEvent.click(screen.getByRole("button", { name: "보내기" }));

  expect(
    await screen.findByText(
      "현재 위치를 확인한 지 30분이 지났어요. 이번 추천에 사용할 위치를 선택해주세요.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "30분 전 위치로 계속" })).toBeInTheDocument();
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);

  await userEvent.click(screen.getByRole("button", { name: "30분 전 위치로 계속" }));
  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2));
  const requestBody = JSON.parse(String(vi.mocked(fetch).mock.calls[1][1]?.body));
  expect(requestBody.user_input).toBe("다른 곳 보여줘");
  expect(requestBody.device_location).toBe("37.5788,126.977");
  now.mockRestore();
});

test("does not ask again within 30 minutes after continuing with the previous location", async () => {
  // "N분 전 위치로 계속"을 누른 뒤 실제 GPS를 다시 받은 게 아닌데도 재확인
  // 질문이 다음 턴마다 반복되던 버그(D 재확인 필요)의 회귀 테스트.
  const now = vi.spyOn(Date, "now");
  now.mockReturnValue(1_000);
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await screen.findByText("테스트 박물관");

  now.mockReturnValue(30 * 60 * 1000 + 1_001);
  await userEvent.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "다른 곳 보여줘");
  await userEvent.click(screen.getByRole("button", { name: "보내기" }));
  await screen.findByText(
    "현재 위치를 확인한 지 30분이 지났어요. 이번 추천에 사용할 위치를 선택해주세요.",
  );
  await userEvent.click(screen.getByRole("button", { name: "30분 전 위치로 계속" }));
  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2));

  // 스누즈 구간(30분) 안의 다음 턴 — 재확인 질문 없이 바로 보내져야 한다.
  now.mockReturnValue(30 * 60 * 1000 + 5 * 60 * 1000 + 1_001);
  await userEvent.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "카페도 보여줘");
  await userEvent.click(screen.getByRole("button", { name: "보내기" }));
  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(3));
  expect(screen.queryByText(/현재 위치를 확인한 지 .*지났어요/)).not.toBeInTheDocument();
  const secondFollowUpBody = JSON.parse(String(vi.mocked(fetch).mock.calls[2][1]?.body));
  expect(secondFollowUpBody.user_input).toBe("카페도 보여줘");
  expect(secondFollowUpBody.device_location).toBe("37.5788,126.977");

  // 스누즈가 끝난 뒤엔 다시 물어야 하고, 실제 GPS 나이(60분)를 그대로 보여줘야
  // 한다 — "이전 위치로 계속"이 나이를 30분으로 리셋해버리면 안 된다.
  now.mockReturnValue(60 * 60 * 1000 + 1_002);
  await userEvent.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "한 곳 더 보여줘");
  await userEvent.click(screen.getByRole("button", { name: "보내기" }));
  expect(
    await screen.findByText(
      "현재 위치를 확인한 지 60분이 지났어요. 이번 추천에 사용할 위치를 선택해주세요.",
    ),
  ).toBeInTheDocument();
  now.mockRestore();
});

test("refreshing a location after 30 minutes requests browser GPS again", async () => {
  const now = vi.spyOn(Date, "now");
  now.mockReturnValue(1_000);
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await screen.findByText("테스트 박물관");

  now.mockReturnValue(30 * 60 * 1000 + 1_001);
  await userEvent.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "카페 추천해줘");
  await userEvent.click(screen.getByRole("button", { name: "보내기" }));
  await screen.findByRole("button", { name: "현재 위치 다시 가져오기" });

  await userEvent.click(screen.getByRole("button", { name: "현재 위치 다시 가져오기" }));

  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2));
  expect(navigator.geolocation.getCurrentPosition).toHaveBeenCalledTimes(2);
  expect(vi.mocked(navigator.geolocation.getCurrentPosition).mock.calls[1][2]).toMatchObject({
    maximumAge: 0,
  });
  now.mockRestore();
});

test("falls back to the existing chat endpoint when the SSE route is unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/chat/stream")) {
        return Response.json(
          {
            error: {
              code: "not_found",
              message: "not found",
              retryable: false,
              details: null,
            },
          },
          { status: 404 },
        );
      }
      return Response.json(chatResponse());
    }),
  );
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(2);
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
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(navigator.geolocation.getCurrentPosition).toHaveBeenCalledTimes(1);
  // 응답을 기다리는 동안엔 안내 문구 한 줄만 뜬다(AgentProgressMessage).
  expect(await screen.findByRole("status")).toHaveTextContent(/중…$/);

  resolveFetch?.(streamResponse());
  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
});

test("developer start opens dev chat with audit panel", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "개발자용으로 시작" }));

  expect(await screen.findByText("Agent Runtime Audit")).toBeInTheDocument();
  expect((await screen.findAllByText(/Intent: RECOMMEND/)).length).toBeGreaterThan(0);
  expect(screen.getByText("TripBranch Developer Console")).toBeInTheDocument();
  // 개발자 화면 상단에도 신원 표시가 이어진다(D-062).
  expect(screen.getByText("게스트로 이용 중")).toBeInTheDocument();
  expect(screen.getAllByText(/비를 피할 실내 장소가 필요해/).length).toBeGreaterThan(1);
});

test("developer audit turn cards remain selectable after multiple turns", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  await renderApp();

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
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText(/위치 권한이 필요해요/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

test("requesting more places sends a follow-up chat turn with the session id", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  await renderApp();

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
      streamResponse({
        llm_output: { ...interpretResponse, recommend: null },
        state: { session_id: "sess_test", run_id: "run_test" },
        recommendations: null,
        message: "어디 근처에서 찾아드릴까요? 현재 위치나 원하시는 지역을 알려주세요.",
      }),
    ),
  );
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText(/어디 근처에서 찾아드릴까요/)).toBeInTheDocument();
  // 발화를 대신 만들어 보내지 않고, 입력창 안내 문구만 바꾼다.
  expect(screen.getByPlaceholderText("예: 경복궁 근처에서 찾아줘")).toBeInTheDocument();
});

test("unsupported region reply shows a short message with the district list as a footnote", async () => {
  // 서비스 지역 밖 요청: 본문은 짧고, 지원 구 목록은 message_footnote로 따로 온다(D-085).
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      streamResponse({
        llm_output: { ...interpretResponse, recommend: null },
        state: { session_id: "sess_test", run_id: "run_test" },
        recommendations: null,
        message: "이 위치는 지금 서비스 지역이 아니에요. 다른 위치를 말씀해 주세요.",
        message_footnote: "현재 서비스 지역: 서울특별시 종로구·중구·용산구·성동구",
      }),
    ),
  );
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(
    await screen.findByText("이 위치는 지금 서비스 지역이 아니에요. 다른 위치를 말씀해 주세요."),
  ).toBeInTheDocument();
  expect(
    screen.getByText("현재 서비스 지역: 서울특별시 종로구·중구·용산구·성동구"),
  ).toBeInTheDocument();
});

test("chat route redirects without stored state", async () => {
  window.history.pushState({}, "", "/chat");

  await renderApp();

  expect(await screen.findByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
});

test("shows follow-up suggestions after an answer and sends the label as the next message", async () => {
  /* 되묻기 버튼과 달리 clarification_choice 없이 문구만 발화로 나간다. */
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await screen.findByText("테스트 박물관");

  const suggestion = await screen.findByRole("button", {
    name: "테스트 박물관 운영시간 알려줘",
  });
  await userEvent.click(suggestion);

  const fetchMock = vi.mocked(fetch);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  const secondBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
  expect(secondBody.user_input).toBe("테스트 박물관 운영시간 알려줘");
  expect(secondBody.clarification_choice).toBeNull();
});

test("keeps only the latest turn's follow-up suggestions", async () => {
  /* 옛 턴의 버튼이 남으면 지난 답변 기준의 문구를 지금 맥락에 보내게 된다. */
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await screen.findByText("테스트 박물관");
  await screen.findByRole("button", { name: "다른 곳도 보여줘" });

  await userEvent.click(screen.getByRole("button", { name: "다른 곳도 보여줘" }));

  await waitFor(() =>
    expect(screen.getAllByRole("group", { name: "이어서 물어볼 만한 질문" })).toHaveLength(1),
  );
});

test("renders no follow-up buttons when the server sends no follow_ups event", async () => {
  /* done 응답에는 문구가 없다 — 버튼은 오직 done 뒤의 follow_ups 이벤트에서 온다. */
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/chat/stream")) {
        return streamResponse({ ...chatResponse(), suggested_follow_ups: [] });
      }
      return Response.json({ error: { message: "not found" } }, { status: 404 });
    }),
  );
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await screen.findByText("테스트 박물관");

  expect(screen.queryByRole("group", { name: "이어서 물어볼 만한 질문" })).not.toBeInTheDocument();
});

// --- 바텀시트 내비게이션(package_D/DESIGN_SYSTEM.md §5) ---------------------

test("사이드바에서 위치 설정을 열면 홈 위에 바텀시트로 뜨고, 닫으면 홈으로 돌아온다", async () => {
  await renderApp();

  // 데스크톱 사이드바(role=complementary)로 좁힌다 — 모바일 드로어도 같은
  // SideDrawerContent를 렌더해 "위치 설정" 텍스트가 중복된다.
  const sidebar = within(screen.getByRole("complementary"));
  await userEvent.click(sidebar.getByRole("button", { name: "위치 설정" }));

  // LocationPage에는 별도 제목이 없다(Figma "Location (Sheet)") — 항상 있는
  // "현재 위치 사용" 버튼으로 시트가 열렸는지 확인한다.
  expect(await screen.findByRole("button", { name: "현재 위치 사용" })).toBeInTheDocument();
  // 시트 모드 헤더는 햄버거·위치 pill 대신 닫기(X) 버튼만 보인다(§6.1). 뒤에
  // 깔리는 어두운 배경도 같은 이름("닫기")의 버튼이라 두 개가 잡힌다(§5.2).
  const closeButtons = screen.getAllByRole("button", { name: "닫기" });
  expect(closeButtons).toHaveLength(2);
  // 새 페이지로 갈아치운 게 아니라 위에 뜬 시트라, 밑에 깔린 홈이 여전히 DOM에 있다.
  expect(screen.getByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();

  await userEvent.click(closeButtons[1]);

  // 닫히는 애니메이션(AnimatePresence exit)이 끝나야 시트가 DOM에서 빠진다.
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "현재 위치 사용" })).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
});

test("사이드바 상시 패널이 보이는 폭(데스크톱)에서는 위치 설정이 시트가 아니라 전체 페이지로 뜬다", async () => {
  // useIsDesktopSidebar가 참을 반환하도록 matchMedia를 데스크톱 폭으로 흉내낸다.
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: true,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }));
  await renderApp();

  const sidebar = within(screen.getByRole("complementary"));
  await userEvent.click(sidebar.getByRole("button", { name: "위치 설정" }));

  expect(await screen.findByRole("button", { name: "현재 위치 사용" })).toBeInTheDocument();
  // 전체 페이지로 그려지므로 시트 모드의 닫기(X)가 아니라 일반 헤더의
  // 뒤로가기가 보이고, 시트 배경에 가려졌던 홈은 더 이상 DOM에 없다.
  expect(screen.queryByRole("button", { name: "닫기" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "뒤로가기" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "추천 시작하기" })).not.toBeInTheDocument();
});

// --- 응답 대기 중 취소(package_D/DESIGN_SYSTEM.md §7.2) ------------------------

test("응답을 기다리는 동안 중단을 누르면 로딩이 멈추고 오류 없이 끝난다", async () => {
  await renderApp();
  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await screen.findByText("테스트 박물관");

  // 후속 발화는 일부러 끝나지 않는 스트림으로 받는다 — 곧바로 완료되면 중단이
  // 실제로 완료 전에 걸리는지 확인할 수 없다.
  let streamController!: ReadableStreamDefaultController<Uint8Array>;
  const pendingStream = new ReadableStream<Uint8Array>({
    start(controller) {
      streamController = controller;
    },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/chat/stream")) {
        // 실제 fetch는 신호가 중단되면 응답 body 스트림도 함께 끊는다 — 이
        // stub도 같은 계약을 흉내 내야 "중단" 버튼이 정말 읽기를 멈추는지
        // 검증할 수 있다.
        init?.signal?.addEventListener("abort", () => {
          streamController.error(new DOMException("The operation was aborted.", "AbortError"));
        });
        return new Response(pendingStream, {
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      return Response.json({ error: { message: "not found" } }, { status: 404 });
    }),
  );

  await userEvent.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "다른 조건 추가");
  await userEvent.click(screen.getByRole("button", { name: "보내기" }));

  // progress 이벤트 하나를 흘려 "생각 중" 상태를 만든다.
  streamController.enqueue(
    new TextEncoder().encode(
      `event: progress\ndata: ${JSON.stringify({
        stage: "interpreting",
        message: "조건을 파악하고 있어요.",
        elapsed_ms: 1,
      })}\n\n`,
    ),
  );

  await userEvent.click(await screen.findByRole("button", { name: "중단" }));

  // 컴포저가 다시 평소의 "보내기" 버튼으로 돌아오고, 오류 배너는 뜨지 않는다.
  expect(await screen.findByRole("button", { name: "보내기" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("텍스트가 이미 온 상태에서 중단하면 거기까지만 남기고 얼린다", async () => {
  await renderApp();
  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await screen.findByText("테스트 박물관");

  let streamController!: ReadableStreamDefaultController<Uint8Array>;
  const pendingStream = new ReadableStream<Uint8Array>({
    start(controller) {
      streamController = controller;
    },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/chat/stream")) {
        init?.signal?.addEventListener("abort", () => {
          streamController.error(new DOMException("The operation was aborted.", "AbortError"));
        });
        return new Response(pendingStream, {
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      return Response.json({ error: { message: "not found" } }, { status: 404 });
    }),
  );

  await userEvent.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "다른 조건 추가");
  await userEvent.click(screen.getByRole("button", { name: "보내기" }));

  const encoder = new TextEncoder();
  streamController.enqueue(
    encoder.encode(
      `event: message_start\ndata: ${JSON.stringify({ intent: "RECOMMEND", elapsed_ms: 1 })}\n\n`,
    ),
  );
  streamController.enqueue(
    encoder.encode(
      `event: message_delta\ndata: ${JSON.stringify({ text: "여기까지 답했어요", elapsed_ms: 2 })}\n\n`,
    ),
  );

  await screen.findByText("여기까지 답했어요");
  await userEvent.click(await screen.findByRole("button", { name: "중단" }));

  // 중단해도 이미 온 텍스트는 사라지지 않고 그대로 남는다.
  expect(await screen.findByRole("button", { name: "보내기" })).toBeInTheDocument();
  expect(screen.getByText("여기까지 답했어요")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  // done 뒤에만 오는 후속 질문은 연결이 끊겼으니 뜨지 않는다.
  expect(screen.queryByRole("group", { name: "이어서 물어볼 만한 질문" })).not.toBeInTheDocument();
});

// --- 홈 화면의 사진 추가 버튼 --------------------------------------------------

test("홈 화면에서도 사진을 올릴 수 있고, 고르면 /chat으로 넘어가 결과를 보여준다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/places/similar-by-photo")) {
        return Response.json({
          places: [
            {
              content_id: "photo-place-1",
              title: "감성 카페",
              similarity: 0.82,
              photo_count: 3,
              address: "서울 성동구",
              image_url: null,
            },
          ],
          center_name: "성수동",
          candidate_count: 12,
          truncated_count: 0,
          elapsed_ms: 400,
        });
      }
      return Response.json({ error: { message: "not found" } }, { status: 404 });
    }),
  );
  await renderApp();

  // 홈 컴포저에도 ChatPage와 같은 "+" 버튼이 있어야 한다(사진 없이는 대화
  // 시작 전에는 이 버튼 자체가 안 그려지는 회귀가 있었다).
  await userEvent.click(screen.getByRole("button", { name: "사진 추가" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "갤러리" }));

  const file = new File(["x"], "cafe.jpg", { type: "image/jpeg" });
  const galleryInput = screen.getByTestId("photo-gallery-input") as HTMLInputElement;
  fireEvent.change(galleryInput, { target: { files: [file] } });

  // 결과는 메시지로 쌓이므로 /chat으로 넘어가야 보인다.
  expect(await screen.findByText("감성 카페")).toBeInTheDocument();
  expect(screen.getByPlaceholderText("추가 조건을 입력해 주세요")).toBeInTheDocument();
});
