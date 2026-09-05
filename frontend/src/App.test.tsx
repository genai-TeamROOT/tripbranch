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
import { setLocationCenter, setLocationOrigin } from "./state/locationSettings";
import { resetChatSessionsCache } from "./state/chatSessions";
import { resetSavedSchedulesCache } from "./state/savedSchedules";
import { resetPreferenceSync } from "./state/preferenceSync";

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
  /* 실제 서버는 조건 병합 직후, 도구 조회·채점·답변 스트리밍보다 앞서 이번 턴이
     쓸 위치를 알려준다(docs/design/agent-response-streaming.md 4.3절). 여기서
     빠뜨리면 화면이 그 이벤트를 안 받는 상태로만 검증된다. */
  const merged = (
    response.state as {
      user_conditions?: { current_location: string | null; search_center: string | null } | null;
    } | null
  )?.user_conditions;
  events.push({
    event: "location_resolved",
    data: {
      current_location: merged?.current_location ?? null,
      search_center: merged?.search_center ?? null,
      elapsed_ms: 2,
    },
  });
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

/*
 * 채팅 관련 호출만 센다. 사이드바가 마운트되면 채팅 히스토리(/sessions)를 함께
 * 받아오는데, 전체 fetch 횟수를 세면 그 부수 요청까지 섞여 "채팅 요청이 몇 번
 * 나갔나"라는 원래 의도가 흐려진다.
 */
function chatCalls() {
  return vi.mocked(fetch).mock.calls.filter((call) => String(call[0]).includes("/chat"));
}

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/chat/stream")) return streamResponse();
    if (url.endsWith("/chat")) {
      return Response.json(chatResponse());
    }
    /* 사이드바 채팅 히스토리(TP-222 후속). 대화 흐름과 무관하지만 사이드바가
       마운트되면 항상 나가므로, 404로 두면 콘솔이 오류로 덮인다. */
    if (url.endsWith("/sessions")) {
      return Response.json({ sessions: [] });
    }
    /* 저장한 일정 목록도 사이드바가 마운트되면 항상 나간다(SCHEDULE 카드 2). */
    if (url.endsWith("/schedules")) {
      return Response.json({ items: [] });
    }
    return Response.json({ error: { message: "not found" } }, { status: 404 });
  });
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  resetChatSessionsCache();
  resetSavedSchedulesCache();
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

  await waitFor(() => expect(chatCalls()).toHaveLength(1));
  expect(String(chatCalls()[0][0])).toContain("/chat");
  const requestBody = JSON.parse(String(chatCalls()[0][1]?.body));
  expect(requestBody.device_location).toBe("37.5788,126.977");
});

test("falls back to the current location instead of the old 종로구 default", async () => {
  /* 위치를 정하지도 않았고 대화도 없다. 그대로 발화하면 기기 좌표를 기준으로
     찾으므로 "종로구"라고 말하면 사실과 다르다 - 지원 지역이 종로구뿐이던 시절의
     기본값이다. */
  await renderApp();

  expect(
    screen.getByRole("button", { name: "위치 설정으로 이동 (현재: 현재 위치)" }),
  ).toBeInTheDocument();
});

test("shows the picked origin in the header pill when no center is set", async () => {
  /* 검색 기준을 비워두면 출발지가 검색 중심이 된다(agent_context의 사다리).
     위치 설정 화면의 칩과 헤더가 같은 사실을 말해야 한다. */
  setLocationOrigin("혜화역");
  await renderApp();

  expect(
    screen.getByRole("button", { name: "위치 설정으로 이동 (현재: 혜화역)" }),
  ).toBeInTheDocument();
});

test("shows the picked search center in the header location pill", async () => {
  /* 고른 위치는 위치 설정 화면이 아니라 상단 위치 pill이 보여준다 - 화면을 나가도
     지금 어디를 기준으로 찾는지가 계속 보여야 한다. */
  setLocationCenter("안국역");
  await renderApp();

  expect(
    screen.getByRole("button", { name: "위치 설정으로 이동 (현재: 안국역)" }),
  ).toBeInTheDocument();
});

test("sends the search center picked on the location screen with the chat request", async () => {
  /* 위치 설정 화면에서 고른 값은 sessionStorage에 남는다(state/searchCenterStorage) —
     화면을 다시 거치지 않고 저장소에 직접 넣고, 발화 요청에 그 값이 실려 나가는지만
     본다. 필드 이름이 어긋나면 화면은 멀쩡한데 위치만 조용히 무시되므로 요청
     본문으로 못 박는다. */
  setLocationCenter("안국역");
  await renderApp();

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "카페 추천해줘",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  /* 이 화면은 발화 말고도 다른 요청을 보내므로(취향 조회 등) 순서로 집지 않고
     /chat 요청을 찾아 본문을 확인한다. */
  const fetchMock = vi.mocked(fetch);
  await waitFor(() =>
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/chat"))).toBe(true),
  );
  const chatCall = fetchMock.mock.calls.find((call) => String(call[0]).includes("/chat"));
  const requestBody = JSON.parse(String(chatCall?.[1]?.body));
  expect(requestBody.selected_search_center).toBe("안국역");
});

/*
 * 발화가 정한 위치를 응답에서 되돌려 받는 흐름. 배선이 한쪽뿐이던 시절에는 위치
 * 설정 화면에서 고른 값만 발화에 실려 나가고, 발화가 그 위치를 바꿔도 저장소는
 * 예전 값을 계속 들고 있었다.
 */
function chatResponseWithConditions(currentLocation: string | null, searchCenter: string | null) {
  return {
    ...chatResponse(),
    state: {
      session_id: "sess_test",
      run_id: "run_test",
      user_conditions: { current_location: currentLocation, search_center: searchCenter },
    },
  };
}

/* 채팅 응답만 갈아끼우고 사이드바 부수 요청(/sessions·/schedules)은 원래대로 둔다. */
function mockFetchWithChatResponse(response: ReturnType<typeof chatResponseWithConditions>) {
  const base = mockFetch();
  return vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).endsWith("/chat/stream")) return streamResponse(response);
    return base(input);
  });
}

/*
 * 이벤트를 두 덩어리로 나눠 흘린다. location_resolved까지만 보낸 채 멈춰 세워야
 * "카드가 뜨기 전에 칩이 이미 바뀌었는가"를 물을 수 있다 — 한 번에 다 보내면
 * 두 시점이 같은 틱에 붙어 순서가 검증되지 않는다.
 */
function gatedStreamResponse(response: ReturnType<typeof chatResponseWithConditions>) {
  const raw = streamResponse(response);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const text = await raw.text();
      const marker = text.indexOf("event: result");
      controller.enqueue(new TextEncoder().encode(text.slice(0, marker)));
      await gate;
      controller.enqueue(new TextEncoder().encode(text.slice(marker)));
      controller.close();
    },
  });
  return {
    response: new Response(stream, { headers: { "Content-Type": "text/event-stream" } }),
    release,
  };
}

test("moves the header pill before the recommendation cards arrive", async () => {
  /* 위치는 조건 병합에서 확정되고 그 뒤 도구 조회·채점이 남는다 — 그 구간이 턴에서
     제일 길다. 결과를 기다렸다가 바꾸면, 사용자는 "광화문역 근처"라고 말해 놓고
     한참 동안 서대문역 기준으로 찾고 있는 줄 안다. */
  setLocationCenter("서대문역");
  const gated = gatedStreamResponse(chatResponseWithConditions("안국역", "광화문역"));
  const base = mockFetch();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/chat/stream")) return gated.response;
      return base(input);
    }),
  );
  await renderApp();

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "지금 안국역인데 광화문역 근처 알려줘",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  /* 아직 result를 안 보냈다 — 칩만 먼저 바뀌어 있어야 한다.

     findBy가 아니라 waitFor로 매번 다시 조회한다. 이 턴은 홈에서 시작해 채팅
     화면으로 넘어가는 중이라, findBy가 홈의 칩을 붙잡은 직후 그 노드가 화면
     교체로 떨어져 나가면 "찾았는데 document에 없다"로 깨진다. */
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "위치 설정으로 이동 (현재: 광화문역)" }),
    ).toBeInTheDocument(),
  );
  expect(screen.queryByText("테스트 박물관")).not.toBeInTheDocument();

  gated.release();
  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
});

test("shows the location the utterance picked in the header pill", async () => {
  /* "지금 안국역인데 광화문역 근처 알려줘" — 발화가 두 위치를 다 말하면 발화가
     이긴다(백엔드 _apply_selected_locations). 그 결과가 화면에 안 돌아오면
     사용자는 아직 서대문역을 기준으로 찾은 줄 안다. */
  setLocationOrigin("서대문역");
  setLocationCenter("서대문역");
  vi.stubGlobal("fetch", mockFetchWithChatResponse(chatResponseWithConditions("안국역", "광화문역")));
  await renderApp();

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "지금 안국역인데 광화문역 근처 알려줘",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  expect(
    await screen.findByRole("button", { name: "위치 설정으로 이동 (현재: 광화문역)" }),
  ).toBeInTheDocument();
});

test("sends the location the utterance picked on the next turn", async () => {
  /* 표시보다 이쪽이 크다. 저장소가 서대문역을 들고 있으면 다음 발화에 그 값이
     selected_search_center로 다시 실려 나가고, 백엔드는 조건 병합보다 앞에서
     그것을 채워 세션의 광화문역을 덮어쓴다 — 대화로 옮긴 위치가 원위치된다. */
  setLocationCenter("서대문역");
  vi.stubGlobal("fetch", mockFetchWithChatResponse(chatResponseWithConditions(null, "광화문역")));
  await renderApp();

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "광화문역 근처 알려줘",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "다른 장소 보기" }));

  await waitFor(() => expect(chatCalls()).toHaveLength(2));
  const requestBody = JSON.parse(String(chatCalls()[1][1]?.body));
  expect(requestBody.selected_search_center).toBe("광화문역");
});

test("keeps the picked location when the server reports no location at all", async () => {
  /* 서버 조건이 비어 오는 대표적인 경우는 세션에 아직 RECOMMEND 조건이 없을 때다
     — 위치를 정해 두고 정보 질문부터 던지면 백엔드 _apply_selected_locations()가
     RECOMMEND에만 걸리므로 user_conditions가 빈 채로 온다. 그때 지우면 질문 하나에
     사용자가 손으로 고른 위치가 사라진다.

     null은 "지우라"가 아니라 "서버도 모른다"는 뜻이라는 것이 이 테스트의 전부라,
     응답 본문 자체는 기본 픽스처를 그대로 쓴다. */
  setLocationCenter("서대문역");
  vi.stubGlobal("fetch", mockFetchWithChatResponse(chatResponseWithConditions(null, null)));
  await renderApp();

  await userEvent.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "경복궁 운영시간 알려줘",
  );
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "위치 설정으로 이동 (현재: 서대문역)" }),
  ).toBeInTheDocument();
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
  expect(chatCalls()).toHaveLength(1);

  await userEvent.click(screen.getByRole("button", { name: "30분 전 위치로 계속" }));
  await waitFor(() => expect(chatCalls()).toHaveLength(2));
  const requestBody = JSON.parse(String(chatCalls()[1][1]?.body));
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
  await waitFor(() => expect(chatCalls()).toHaveLength(2));

  // 스누즈 구간(30분) 안의 다음 턴 — 재확인 질문 없이 바로 보내져야 한다.
  now.mockReturnValue(30 * 60 * 1000 + 5 * 60 * 1000 + 1_001);
  await userEvent.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "카페도 보여줘");
  await userEvent.click(screen.getByRole("button", { name: "보내기" }));
  await waitFor(() => expect(chatCalls()).toHaveLength(3));
  expect(screen.queryByText(/현재 위치를 확인한 지 .*지났어요/)).not.toBeInTheDocument();
  const secondFollowUpBody = JSON.parse(String(chatCalls()[2][1]?.body));
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

  await waitFor(() => expect(chatCalls()).toHaveLength(2));
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
  expect(chatCalls()).toHaveLength(2);
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
  /* 위치 권한이 거부되면 추천 요청 자체가 나가지 않는다. 사이드바 히스토리
     같은 부수 요청은 이 판단과 무관하므로 채팅 호출만 본다. */
  expect(chatCalls()).toHaveLength(0);
});

test("requesting more places sends a follow-up chat turn with the session id", async () => {
  vi.stubEnv("VITE_SHOW_INTERPRETATION_DEBUG", "false");
  await renderApp();

  await userEvent.click(screen.getByText("비를 피할 실내 장소가 필요해"));
  await userEvent.click(screen.getByRole("button", { name: "추천 시작하기" }));

  expect(await screen.findByText("테스트 박물관")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "다른 장소 보기" }));

  await waitFor(() => expect(screen.getAllByText("테스트 박물관")).toHaveLength(2));
  expect(chatCalls()).toHaveLength(2);
  const requestBody = JSON.parse(String(chatCalls()[1][1]?.body));
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

  await waitFor(() => expect(chatCalls()).toHaveLength(2));
  const secondBody = JSON.parse(String(chatCalls()[1][1]?.body));
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

/*
 * 일정도 위치와 같은 시트 경로를 탄다(state/sheetNav.ts의 SHEET_PATH_PATTERNS).
 * SchedulePage 자체는 별도 파일에서 직접 렌더해 검증하고, 여기서는 "사이드바에서
 * 눌렀을 때 홈을 갈아치우지 않고 그 위에 뜨는가"만 본다 — 이 배선이 빠지면
 * 대화가 사라진다.
 */
test("사이드바에서 일정을 열면 홈 위에 바텀시트로 뜬다", async () => {
  await renderApp();

  const sidebar = within(screen.getByRole("complementary"));
  await userEvent.click(sidebar.getByRole("button", { name: "일정" }));

  expect(await screen.findByText("아직 짠 일정이 없어요.")).toBeInTheDocument();
  // 밑에 깔린 홈이 그대로 있어야 시트다(전체 페이지 전환이면 사라진다).
  expect(screen.getByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "닫기" })).toHaveLength(2);
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

/*
 * 취향 설정은 별도 전체 화면이라, 뭘 골라뒀는지 확인하려면 거기까지 들어갔다
 * 와야 했다. 홈에서 한 번 더 보여줘 그 왕복을 없앤다.
 */
test("저장해 둔 취향을 홈 화면에서 다시 보여준다", async () => {
  /*
   * 취향 동기화는 페이지 로드당 한 번만 도는 모듈 캐시다. 앞 테스트들이 이미
   * 빈 결과로 채워두므로, 여기서 비우지 않으면 심어둔 값이 그 빈 결과로 덮인다.
   * beforeEach에 넣지 않는 이유는 자기만의 fetch를 세우는 테스트들이 /preferences
   * 응답까지 흉내 내지 않아, 동기화가 실제로 돌면 그쪽이 깨지기 때문이다.
   */
  resetPreferenceSync();
  localStorage.setItem(
    "tb_preferences",
    JSON.stringify([
      { label: "조용한 곳", source: "preference", codes: ["quiet"] },
      { label: "카페", source: "place_tag", codes: ["카페", "찻집"] },
      { label: "데이트 코스", source: "preference", codes: ["date"] },
    ]),
  );
  await renderApp();

  const section = screen.getByRole("heading", { name: "내 취향" }).closest("section");
  expect(section).not.toBeNull();
  expect(within(section as HTMLElement).getByText("조용한 곳")).toBeInTheDocument();
  expect(within(section as HTMLElement).getByText("카페")).toBeInTheDocument();
  expect(within(section as HTMLElement).getByText("데이트 코스")).toBeInTheDocument();

  // 홈에서는 읽기만 한다 — 고치려면 취향 설정 화면으로 간다.
  expect(within(section as HTMLElement).getByRole("link", { name: "바꾸기" })).toHaveAttribute(
    "href",
    "/preferences",
  );
});

test("저장해 둔 취향이 없으면 홈에 그 줄을 그리지 않는다", async () => {
  /* 앞 테스트가 심어둔 값이 모듈 캐시에 남는다 — 위와 같은 이유로 여기서도 비운다. */
  resetPreferenceSync();
  await renderApp();

  expect(screen.queryByRole("heading", { name: "내 취향" })).not.toBeInTheDocument();
});
