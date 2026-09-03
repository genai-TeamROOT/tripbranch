/*
 * 역할: 사이드바(셸 + SideDrawerContent)의 동작을 앱 통합 수준에서 검증한다.
 * 입력: 렌더된 App, 사용자 클릭·입력.
 * 출력: 즐겨찾기·채팅 히스토리 편집, 접힘 전환, 라우트 이동에 대한 assertion.
 * 호출 시점: vitest 실행 시.
 *
 * **즐겨찾기와 채팅 히스토리는 사는 곳이 다르다.** 즐겨찾기는 아직 localStorage
 * 목업이고(state/sidebarStorage.ts), 채팅 히스토리는 계정에서 온다
 * (GET /api/sessions, TP-222 후속). 그래서 씨앗도 각각 다른 곳에 심는다.
 *
 * 이름 바꾸기·삭제는 화면만 바꾸는 것이 아니라 서버에도 보내야 한다 — 화면에서만
 * 사라지고 서버에 남으면 다음에 열었을 때 되살아난다.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import App from "../../App";
import { resetChatSessionsCache } from "../../state/chatSessions";
import { resetSavedSchedulesCache } from "../../state/savedSchedules";
import { isDetachedRequest } from "../../state/chatAbortController";
import { GUEST_SESSION, setMockSession } from "../../test/supabaseMock";

const SEED_FAVORITES = [
  { id: "fav-1", label: "회사 (역삼동)" },
  { id: "fav-2", label: "집 (성수동)" },
];

/** 계정에 쌓인 대화. 서버가 주는 모양 그대로다. */
const server = vi.hoisted(() => ({
  sessions: [] as { session_id: string; title: string; location: string | null; last_active_at: string }[],
  renamed: [] as { id: string; title: string }[],
  deleted: [] as string[],
  resumed: [] as string[],
  /* 한 턴의 화면 기록. payload는 그 턴의 AgentResponse 그대로다. */
  transcript: {
    session_id: "chat-1",
    run_id: "run_1",
    user_id: null,
    user_input: "비 오는데 어디 갈까",
    recorded_at: "2026-09-03T08:58:23+09:00",
    payload: {
      llm_output: { intent: "RECOMMEND", status: "complete" },
      state: { session_id: "chat-1", run_id: "run_1" },
      message: "실내를 찾아볼게요",
      recommendations: {
        recommendations: [
          {
            place_id: "p1",
            name: "국립중앙박물관",
            category: "문화시설",
            distance_km: 1.2,
            remaining_minutes: 180,
            environment_type: "indoor",
            recommendation_reason: "비 오는 날 실내에서 오래 머물기 좋아요",
            explanations: [],
            warnings: [],
            score: 0.81,
            feature_scores: {},
            weights_used: {},
            taste_evidence: [],
          },
        ],
        unverified_recommendations: [],
        elapsed_ms: 1200,
      },
    },
  },
  /** 이어서 보낸 발화가 실어 나간 session_id. null이면 새 대화로 간 것이다. */
  chatSessionIds: [] as (string | null)[],
  /** GET /api/sessions를 실제로 부른 횟수. 사이드바 두 벌이 겹쳐 부르는지 본다. */
  listCalls: 0,
  /** 계정에 저장한 일정(SCHEDULE 카드 2). 대화와 별도 저장소라 따로 심는다. */
  schedules: [] as { id: string; title: string; session_id: string | null; created_at: string; updated_at: string }[],
  /*
   * 두 턴짜리 화면 기록. 두 턴 모두 후속 질문을 달아 둔다 — 복원했을 때
   * 마지막 턴에만 버튼이 남아야 한다.
   */
  transcriptTurns() {
    return [
      {
        ...server.transcript,
        user_input: "첫 질문",
        payload: {
          ...server.transcript.payload,
          message: "첫 답변",
          recommendations: null,
          suggested_follow_ups: ["첫 턴의 후속 질문"],
        },
      },
      {
        ...server.transcript,
        payload: {
          ...server.transcript.payload,
          suggested_follow_ups: ["마지막 턴의 후속 질문"],
        },
      },
    ];
  },
  /** 켜면 기록이 말풍선보다 모자란 대화를 흉내 낸다(저장이 한 번 실패한 경우). */
  partialTranscript: false,
  /** 켜면 지난 대화 열기가 실패한다. */
  resumeFails: false,
  /** 켜면 streamChat이 응답을 붙들고 있는다 — 답변 대기 중 상황을 만든다. */
  holdStream: false,
  pending: null as ((event: { type: string; data: unknown }) => void) | null,
  releaseStream: null as (() => void) | null,
}));

vi.mock("../../api/trip", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/trip")>();
  return {
    ...actual,
    fetchChatSessions: async () => {
      server.listCalls += 1;
      return { sessions: server.sessions };
    },
    fetchSavedSchedules: async () => ({ items: server.schedules }),
    /* 사이드바는 조회가 아니라 resume을 부른다 — 만료된 대화를 되살려야 이어
       물었을 때 같은 세션에 붙는다. resume의 응답은 항상 resumable: true다. */
    resumeChatSession: async (sessionId: string) => {
      const found = server.sessions.find((item) => item.session_id === sessionId);
      if (!found || server.resumeFails) throw new Error("없는 대화");
      server.resumed.push(sessionId);
      return {
        session_id: sessionId,
        title: found.title,
        /* 추천은 그 턴이 기록되기 전에 남는다(실측 평균 97초 먼저). */
        recommendations: [
          { place_id: "p1", run_id: "run_1", name: "국립중앙박물관", rank: 1, distance_km: 1.2, environment_type: "indoor", reason: null, shown_at: "2026-09-03T08:58:23+09:00" },
        ],
        /* 화면 기록. 있으면 화면은 turns/recommendations 대신 이것만 쓴다.
           chat-1에만 둬서 두 경로를 한 파일에서 함께 본다. */
        /* 화면 기록으로 되돌릴 수 있는지는 **백엔드가 판정해서 알려준다.**
           chat-1은 기록이 온전하고, chat-2는 기록이 없는 옛 대화다.
           partialTranscript를 켜면 저장이 한 번 실패한 대화가 된다. */
        restore_from_messages: sessionId === "chat-1" && !server.partialTranscript,
        /* **온전하지 않아도 기록은 함께 온다.** 서버는 있는 것을 그대로 주고
           쓸지 말지는 restore_from_messages가 정한다 — 화면이 messages가
           비었는지로 판단하면 이 경우를 놓친다. */
        messages: sessionId === "chat-1" ? server.transcriptTurns() : [],
        turns: server.partialTranscript
          ? [
              { user_input: "첫 질문", assistant_message: "첫 답변", intent: "RECOMMEND", place_names: [], at: "2026-09-03T09:00:00+09:00" },
              { user_input: "빠진 질문", assistant_message: "빠진 답변", intent: "RECOMMEND", place_names: [], at: "2026-09-03T09:05:00+09:00" },
            ]
          : [
              { user_input: "비 오는데 어디 갈까", assistant_message: "실내를 찾아볼게요", intent: "RECOMMEND", place_names: [], at: "2026-09-03T09:00:00+09:00" },
            ],
        last_active_at: found.last_active_at,
        resumable: true,
      };
    },
    /*
     * 한 턴을 끝까지 흉내 낸다. done을 보내지 않으면 phase가 ready가 되지 않아
     * "턴이 끝났을 때"에 걸린 동작(사이드바 목록 갱신)을 볼 수 없다.
     */
    streamChat: async (
      request: { session_id: string | null; user_input: string },
      onEvent: (event: { type: string; data: unknown }) => void,
      signal?: AbortSignal,
    ) => {
      /* 응답이 늦게 오는 상황을 만든다. 테스트가 직접 done을 쏠 수 있게 콜백을
         넘겨두고, 실제 SSE와 같이 끊기면 AbortError로 끝난다. */
      if (server.holdStream) {
        /* 실제 streamChat과 같은 판정이다 — 끊겼거나 화면에서 떼어진 요청의
           이벤트는 흘리지 않는다. 떼어내기는 요청을 끊지 않으므로 aborted만
           보면 이 경우를 놓친다. */
        server.pending = (event) => {
          if (signal?.aborted || isDetachedRequest(signal)) return;
          onEvent(event);
        };
        await new Promise<void>((resolve, reject) => {
          server.releaseStream = resolve;
          signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
        return;
      }
      server.chatSessionIds.push(request.session_id);
      /* 서버는 첫 턴에 세션을 만들고 그 발화를 제목으로 붙인다. */
      const sessionId = request.session_id ?? "chat-new";
      if (!server.sessions.some((item) => item.session_id === sessionId)) {
        server.sessions = [
          {
            session_id: sessionId,
            title: request.user_input,
            location: null,
            last_active_at: "2026-09-03T10:00:00+09:00",
          },
          ...server.sessions,
        ];
      }
      onEvent({
        type: "done",
        data: {
          elapsed_ms: 10,
          response: {
            ...server.transcript.payload,
            state: { session_id: sessionId, run_id: "run_new" },
            message: "찾아볼게요",
            recommendations: null,
          },
        },
      });
    },
    renameChatSession: async (sessionId: string, title: string) => {
      server.renamed.push({ id: sessionId, title });
      server.sessions = server.sessions.map((item) =>
        item.session_id === sessionId ? { ...item, title } : item,
      );
      return { ...server.sessions[0], title };
    },
    deleteChatSession: async (sessionId: string) => {
      server.deleted.push(sessionId);
      server.sessions = server.sessions.filter((item) => item.session_id !== sessionId);
      return { session_id: sessionId, deleted: true };
    },
  };
});

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  localStorage.setItem("tb_favorites", JSON.stringify(SEED_FAVORITES));
  window.history.pushState({}, "", "/");
  resetChatSessionsCache();
  resetSavedSchedulesCache();
  server.schedules = [];
  server.sessions = [
    {
      session_id: "chat-1",
      title: "비 오는 날 아이와 함께 갈 곳",
      location: null,
      last_active_at: "2026-09-03T09:00:00+09:00",
    },
    {
      session_id: "chat-2",
      title: "갑자기 뜬 2시간, 카페 추천",
      location: "성수동",
      last_active_at: "2026-09-02T09:00:00+09:00",
    },
  ];
  server.renamed = [];
  server.deleted = [];
  server.resumed = [];
  server.chatSessionIds = [];
  server.listCalls = 0;
  server.partialTranscript = false;
  server.resumeFails = false;
  server.holdStream = false;
  server.pending = null;
  server.releaseStream = null;
  /*
   * 홈의 첫 발화는 위치를 먼저 얻고 나서야 streamChat을 부른다. 위치를 못 얻으면
   * 안내 문구만 뜨고 요청이 나가지 않는다 — 그 경로를 쓰는 테스트가 통째로 죽는다.
   *
   * 두 갈래를 모두 테스트 안에서 고정한다. 로컬 .env의 테스트 좌표
   * (VITE_TEST_DEVICE_LOCATION)에 기대면 그 파일이 없는 CI에서만 깨지고,
   * jsdom에는 navigator.geolocation이 없다(App.test.tsx와 같은 이유).
   */
  vi.stubEnv("VITE_TEST_DEVICE_LOCATION", "");
  /* navigator를 통째로 갈아끼우지 않는다 — userEvent가 쓰는 clipboard·userAgent가
     함께 사라진다. 없는 속성 하나만 얹는다. */
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: {
      getCurrentPosition: (success: PositionCallback) =>
        success({
          coords: { latitude: 37.5788, longitude: 126.977 },
          timestamp: Date.now(),
        } as GeolocationPosition),
    },
  });
});

/*
 * 렌더 직후에는 게스트 세션 조회가 끝나지 않아 관문(RequireUser)이 로딩 문구만
 * 그린다. 셸이 붙을 때까지 기다린 뒤에 사이드바를 만진다(App.test.tsx와 같은 이유).
 */
async function renderApp() {
  render(<App />);
  await screen.findByRole("button", { name: "추천 시작하기" });
  /* 채팅 히스토리는 계정에서 비동기로 온다. 셸만 기다리면 목록이 아직 비어 있어
     "메뉴" 버튼을 찾을 수 없다. */
  await waitFor(() =>
    expect(within(sidebar()).getByText("비 오는 날 아이와 함께 갈 곳")).toBeInTheDocument(),
  );
}

/** 사이드바는 셸 안에 상시 렌더된다. jsdom에는 CSS가 없어 폭 분기와 무관하게 잡힌다. */
function sidebar() {
  return screen.getByRole("complementary");
}

test("저장된 즐겨찾기가 사이드바에 보인다", async () => {
  await renderApp();

  expect(within(sidebar()).getByText("회사 (역삼동)")).toBeInTheDocument();
  expect(within(sidebar()).getByText("집 (성수동)")).toBeInTheDocument();
});

test("즐겨찾기를 추가하면 목록에 남는다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "추가" }));

  // 모달의 제출 버튼과 사이드바의 "+ 추가"가 이름이 같다. 모달 안으로 범위를 좁힌다.
  const modal = screen.getByRole("dialog", { name: "즐겨찾기 추가" });
  await user.type(within(modal).getByRole("textbox"), "학교 (신촌)");
  await user.click(within(modal).getByRole("button", { name: "추가" }));

  expect(within(sidebar()).getByText("학교 (신촌)")).toBeInTheDocument();
});

test("즐겨찾기를 삭제하면 목록에서 빠진다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "회사 (역삼동) 즐겨찾기 삭제" }));

  expect(within(sidebar()).queryByText("회사 (역삼동)")).not.toBeInTheDocument();
  expect(within(sidebar()).getByText("집 (성수동)")).toBeInTheDocument();
});

test("채팅 히스토리 이름을 바꾸면 새 이름이 남는다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(
    within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 메뉴" }),
  );
  await user.click(screen.getByRole("menuitem", { name: "이름 바꾸기" }));

  const input = screen.getByRole("textbox", { name: "대화 이름" });
  await user.clear(input);
  await user.type(input, "비 오는 날 실내 코스{Enter}");

  expect(within(sidebar()).getByText("비 오는 날 실내 코스")).toBeInTheDocument();
  expect(within(sidebar()).queryByText("비 오는 날 아이와 함께 갈 곳")).not.toBeInTheDocument();
});

test("채팅 히스토리를 삭제하면 목록에서 빠진다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(
    within(sidebar()).getByRole("button", { name: "갑자기 뜬 2시간, 카페 추천 메뉴" }),
  );
  await user.click(screen.getByRole("menuitem", { name: "삭제" }));

  expect(within(sidebar()).queryByText("갑자기 뜬 2시간, 카페 추천")).not.toBeInTheDocument();
});

test("사이드바를 접으면 레일만 남고 다시 펼칠 수 있다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(screen.getByRole("button", { name: "사이드바 접기" }));

  // 접힘 레일에는 아이콘만 남는다 — 목록 제목이 사라진다.
  expect(within(sidebar()).queryByText("즐겨찾기")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "사이드바 펼치기" }));
  expect(within(sidebar()).getByText("즐겨찾기")).toBeInTheDocument();
});

test("취향 설정으로 이동하면 취향 선택 화면이 뜬다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "취향 설정" }));

  expect(screen.getByText(/끌리시나요/)).toBeInTheDocument();
});

/* 화면에서만 지우고 서버에 남기면 다음에 열었을 때 되살아난다. */
test("이름 바꾸기와 삭제가 서버까지 간다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(
    within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 메뉴" }),
  );
  await user.click(screen.getByRole("menuitem", { name: "이름 바꾸기" }));
  const input = screen.getByRole("textbox", { name: "대화 이름" });
  await user.clear(input);
  await user.type(input, "새 이름{Enter}");

  await waitFor(() => expect(server.renamed).toEqual([{ id: "chat-1", title: "새 이름" }]));

  await user.click(within(sidebar()).getByRole("button", { name: "갑자기 뜬 2시간, 카페 추천 메뉴" }));
  await user.click(screen.getByRole("menuitem", { name: "삭제" }));

  await waitFor(() => expect(server.deleted).toEqual(["chat-2"]));
});

/* 장소 이름이 아니라 위치다 — "블루보틀 성수"는 그 대화가 무엇이었는지
   말해주지 않지만 "성수동"은 말해준다. */
test("대화의 위치가 목록에 함께 보인다", async () => {
  await renderApp();

  expect(within(sidebar()).getByText("성수동")).toBeInTheDocument();
});


/* 목록만 만들고 못 열게 두면 "눌러도 아무 일이 없는" 화면이 된다. */
test("히스토리를 누르면 지난 대화가 채팅 화면에 펼쳐진다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));

  expect(await screen.findByText("비 오는데 어디 갈까")).toBeInTheDocument();
  expect(screen.getByText("실내를 찾아볼게요")).toBeInTheDocument();
});

/* 보이는 말풍선은 최근 5턴뿐이라 대화 전체가 아니다. 말없이 두면 사용자는
   이게 전부인 줄로 안다. */
test("옛 대화를 열면 앞부분이 없다고 밝힌다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "갑자기 뜬 2시간, 카페 추천 대화 열기" }));

  expect(await screen.findByText(/앞부분은 남아 있지 않아요/)).toBeInTheDocument();
});

/*
 * 이 파일에서 가장 중요한 테스트다. 화면 기록을 따로 저장한 목적이 이것이다 —
 * 지난 대화가 "비슷하게"가 아니라 **그때 그대로** 나와야 한다. 실시간과 같은
 * buildAgentMessages를 태우므로 진짜 추천 카드가 그려진다.
 */
test("화면 기록이 있으면 그때 본 화면 그대로 펼쳐진다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));

  expect(await screen.findByText("실내를 찾아볼게요")).toBeInTheDocument();
  /* 근사치 카드("그때 추천받은 곳")가 아니라 실제 추천 카드다 — 추천 이유까지 나온다. */
  expect(screen.getByText("추천 장소")).toBeInTheDocument();
  expect(screen.getByText("국립중앙박물관")).toBeInTheDocument();
  expect(screen.getByText("비 오는 날 실내에서 오래 머물기 좋아요")).toBeInTheDocument();
  expect(screen.queryByText("그때 추천받은 곳")).not.toBeInTheDocument();
});

/* 화면 기록이 쌓이기 전의 옛 대화. 손실은 있지만 통째로 안 보이는 것보다 낫다. */
test("화면 기록이 없는 옛 대화는 저장된 조각으로 펼쳐진다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "갑자기 뜬 2시간, 카페 추천 대화 열기" }));

  expect(await screen.findByText("그때 추천받은 곳")).toBeInTheDocument();
  expect(screen.getByText("국립중앙박물관")).toBeInTheDocument();
  /* 저장된 값만 보여준다 — 거리·실내외는 있고 점수·운영시간은 기록이 없다. */
  expect(screen.getByText("1.2km · 실내")).toBeInTheDocument();
});

/* 옛 대화만 "마지막 부분"이다. 전체가 나오는데 그렇게 말하면 거짓이 된다. */
/* 기록이 온전한 대화에는 시각만 뜨고, 빠진 게 있다는 말은 붙지 않는다. */
test("화면 기록이 온전하면 앞부분이 없다고 말하지 않는다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));

  /* 날짜 표기는 오늘·어제면 그렇게 부르므로 실행 날짜에 따라 달라진다.
     이 테스트가 보는 것은 "시각이 뜨고, 빠진 게 있다는 말은 없다"다.
     **시각도 브라우저 시간대를 따른다** — KST 기준으로 적어 두면 UTC로 도는
     CI에서만 깨진다. 기록된 시각을 화면과 같은 방식으로 포맷해 견준다. */
  const shownAt = new Date(server.transcript.recorded_at)
    .toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" })
    .replace(/\s+/g, " ");
  expect(await screen.findByText(new RegExp(shownAt))).toBeInTheDocument();
  expect(screen.queryByText(/앞부분은 남아 있지 않아요/)).not.toBeInTheDocument();
});

/*
 * 이 파일에서 가장 중요한 테스트다. 지난 대화를 여는 목적은 읽는 것이 아니라
 * 이어가는 것이고, 그건 다음 발화가 **같은 session_id**를 실어 나가야만
 * 성립한다. 비어서 나가면 백엔드가 새 세션을 만들어 목록에 줄이 하나 더 생긴다.
 */
test("지난 대화를 열고 이어 물으면 같은 세션으로 나간다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));
  await screen.findByText("비 오는데 어디 갈까");
  await user.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "그럼 근처 카페는?{Enter}");

  await waitFor(() => expect(server.chatSessionIds).toEqual(["chat-1"]));
  expect(server.resumed).toEqual(["chat-1"]);
});


/*
 * 새로고침해야 목록에 나타나면 방금 한 대화가 없는 것처럼 보인다.
 *
 * 사이드바가 두 벌 마운트돼 있어(데스크톱 패널 + 모바일 드로어) 같은 계기에
 * 둘 다 목록을 다시 받아오려 하는데, 겹쳐도 서버는 한 번만 부른다.
 */
test("새 대화를 시작하면 새로고침 없이 목록에 뜬다", async () => {
  const user = userEvent.setup();
  await renderApp();
  const before = server.listCalls;

  await user.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "방금 시작한 대화",
  );
  await user.click(screen.getByRole("button", { name: "추천 시작하기" }));

  await waitFor(() =>
    expect(within(sidebar()).getByText("방금 시작한 대화")).toBeInTheDocument(),
  );
  /* 두 벌이 동시에 물어도 요청은 하나다. */
  expect(server.listCalls - before).toBe(1);
});


/*
 * 답변을 기다리는 중에 다른 대화를 열면, 오던 답변이 **그 대화에** 붙는 버그가
 * 있었다. 요청은 앞 대화의 것이라 서버에는 앞 대화로 저장되는데 화면만 다른
 * 대화에 나타난다 — 사용자는 하지도 않은 질문의 답을 보게 된다.
 */
test("답변 대기 중에 다른 대화를 열면 그 답변이 따라오지 않는다", async () => {
  const user = userEvent.setup();
  await renderApp();
  server.holdStream = true;

  await user.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "앞 대화의 질문",
  );
  await user.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await waitFor(() => expect(server.pending).not.toBeNull());

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));
  await screen.findByText("실내를 찾아볼게요");

  /* 뒤늦게 도착한 앞 대화의 답변. 끊긴 요청이라 화면에 닿으면 안 된다. */
  server.pending?.({
    type: "done",
    data: {
      elapsed_ms: 10,
      response: {
        ...server.transcript.payload,
        state: { session_id: "chat-앞", run_id: "run_앞" },
        message: "앞 대화의 답변",
        recommendations: null,
      },
    },
  });
  server.releaseStream?.();

  /* **없음을 확인하려면 먼저 흘려보내야 한다.** waitFor는 조건이 처음부터
     참이면 그 자리에서 끝나므로, 늦게 도착할 답변을 기다리지 않고 통과한다. */
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  expect(screen.queryByText("앞 대화의 답변")).not.toBeInTheDocument();
  expect(screen.getByText("실내를 찾아볼게요")).toBeInTheDocument();
});


/*
 * 목록에 여러 줄이 있는데 어느 것이 열려 있는지 표시가 없으면, 대화를
 * 이어가면서도 자기가 어디 있는지 모른다.
 */
test("지금 보고 있는 대화가 목록에서 표시된다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));
  await screen.findByText("실내를 찾아볼게요");

  const rows = within(sidebar()).getAllByRole("listitem");
  const current = rows.filter((row) => row.getAttribute("aria-current") === "true");
  expect(current).toHaveLength(1);
  expect(current[0]).toHaveTextContent("비 오는 날 아이와 함께 갈 곳");
});

/* 홈처럼 세션이 없는 화면에서는 아무 줄도 켜지지 않아야 한다. */
test("대화를 열기 전에는 켜진 줄이 없다", async () => {
  await renderApp();

  const rows = within(sidebar()).getAllByRole("listitem");
  expect(rows.filter((row) => row.getAttribute("aria-current") === "true")).toEqual([]);
});


/* 실시간에서도 새 발화가 나가면 옛 버튼은 걷힌다. 전부 되살리면 지난 답변
   기준의 문구를 눌러 지금 맥락과 어긋난 요청이 나간다. */
test("복원한 대화의 후속 질문은 마지막 답변에만 남는다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));
  await screen.findByText("첫 답변");

  expect(screen.getByRole("button", { name: "마지막 턴의 후속 질문" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "첫 턴의 후속 질문" })).not.toBeInTheDocument();
});

/*
 * 화면에 실제로 나가는 순서는 카드가 먼저고 답변이 그 아래다(스트리밍이 result를
 * 먼저 내보낸다). 되돌릴 때 답변을 위에 놓으면 그때 본 화면과 위아래가 뒤집힌다.
 */
test("복원한 대화에서 추천 카드가 답변보다 위에 온다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));

  const card = await screen.findByText("국립중앙박물관");
  const answer = screen.getByText("실내를 찾아볼게요");
  expect(card.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});


/*
 * 기록 저장이 실패해도 응답은 막지 않는다(그게 맞다). 그래서 턴 하나가 빠진
 * 기록이 있을 수 있는데, "하나라도 있으면 기록만 쓴다"로 판정하면 그 대화는
 * **조용히 일부만** 보인다 — 사용자는 자기가 한 말이 사라진 것으로 본다.
 */
test("기록이 온전하지 않으면 예전 방식으로 되돌린다", async () => {
  const user = userEvent.setup();
  server.partialTranscript = true;
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));

  /* 기록에 없던 턴까지 나온다 — 저장된 말풍선으로 되돌렸다는 뜻이다. */
  expect(await screen.findByText("빠진 질문")).toBeInTheDocument();
  /* 그리고 전부가 아니라는 것을 화면이 밝힌다. */
  expect(screen.getByText(/앞부분은 남아 있지 않아요/)).toBeInTheDocument();
});


/* 열기가 실패하면 화면은 그대로 남는다. 그런데 오던 답변까지 버리면, 아무 일도
   일어나지 않은 것처럼 보이면서 기다리던 답변만 사라진다. */
test("지난 대화 열기가 실패하면 오던 답변을 버리지 않는다", async () => {
  const user = userEvent.setup();
  await renderApp();
  server.holdStream = true;

  await user.type(
    screen.getByPlaceholderText(
      "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    ),
    "기다리던 질문",
  );
  await user.click(screen.getByRole("button", { name: "추천 시작하기" }));
  await waitFor(() => expect(server.pending).not.toBeNull());

  server.resumeFails = true;
  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));
  await waitFor(() => expect(server.listCalls).toBeGreaterThan(1));

  /* 열기는 실패했으니 답변은 그대로 도착해야 한다. */
  server.pending?.({
    type: "done",
    data: {
      elapsed_ms: 10,
      response: {
        ...server.transcript.payload,
        state: { session_id: "chat-대기", run_id: "run_대기" },
        message: "기다리던 답변",
        recommendations: null,
      },
    },
  });
  server.releaseStream?.();

  expect(await screen.findByText("기다리던 답변")).toBeInTheDocument();
});


/*
 * 보고 있는 대화를 지웠는데 화면에 그대로 두면, 이어 물었을 때 없는 session_id가
 * 나가 백엔드가 조용히 새 세션을 만든다 — 사용자는 같은 대화를 이어간 줄로 안다.
 */
test("보고 있는 대화를 지우면 화면도 비운다", async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));
  await screen.findByText("실내를 찾아볼게요");

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 메뉴" }));
  await user.click(screen.getByRole("menuitem", { name: "삭제" }));

  await waitFor(() => expect(screen.queryByText("실내를 찾아볼게요")).not.toBeInTheDocument());
});

/* 다른 대화를 지우는 것은 보고 있는 대화에 영향이 없어야 한다. */
test("다른 대화를 지워도 보고 있는 대화는 그대로다", async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));
  await screen.findByText("실내를 찾아볼게요");

  await user.click(within(sidebar()).getByRole("button", { name: "갑자기 뜬 2시간, 카페 추천 메뉴" }));
  await user.click(screen.getByRole("menuitem", { name: "삭제" }));

  expect(screen.getByText("실내를 찾아볼게요")).toBeInTheDocument();
});


/*
 * 자리를 비웠다가 돌아와 이어 묻는 발화 위에는 지금 시각이 뜬다. 위쪽 지난
 * 대화와 아래쪽 새 발화가 언제 오간 것인지 갈라 보이게 하는 것이 목적이다.
 */
test("지난 대화를 이어가면 새 발화 위에 지금 시각이 뜬다", async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));
  await screen.findByText("실내를 찾아볼게요");
  const before = screen.getAllByText(/오전|오후/).length;

  await user.type(screen.getByPlaceholderText("추가 조건을 입력해 주세요"), "이어서 물어봄{Enter}");

  await waitFor(() => expect(screen.getAllByText(/오전|오후/).length).toBe(before + 1));
});

/*
 * 게스트가 계정으로 넘어가는 유일한 입구다(D-062 8절).
 *
 * **이 입구가 없으면 승계 코드가 있어도 도달할 수 없다.** /signup 링크는 로그인
 * 관문에만 있는데 게스트는 세션이 있어서 그 화면에서 곧바로 되돌려보내진다
 * (LoginPage의 Navigate). 그래서 가입하려면 먼저 로그아웃해야 했고, 로그아웃하면
 * 그 uid로 돌아갈 길이 없어 이어받을 기록 자체가 사라졌다.
 */

test("게스트에게는 계정 만들기 입구가 보이고 가입 화면으로 간다", async () => {
  await renderApp();

  const enter = within(sidebar()).getByRole("button", { name: /계정 만들기/ });
  await userEvent.click(enter);

  /* 가입 화면이 열려야 승계가 시작된다. */
  expect(await screen.findByRole("button", { name: "가입하고 시작하기" })).toBeInTheDocument();
});

test("이미 계정이 있으면 계정 만들기 입구를 보여주지 않는다", async () => {
  setMockSession({
    ...GUEST_SESSION,
    user: { ...GUEST_SESSION.user, is_anonymous: false, email: "trip@example.com" },
  } as typeof GUEST_SESSION);

  await renderApp();

  expect(within(sidebar()).queryByRole("button", { name: /계정 만들기/ })).not.toBeInTheDocument();
  expect(within(sidebar()).getByText("trip@example.com")).toBeInTheDocument();
});

/*
 * 게스트에게 로그아웃은 되돌릴 수 없다 — 다시 로그인할 수단이 없어 그 uid로
 * 돌아갈 길이 사라지고, 거기 달린 대화도 함께 닿을 수 없게 된다. 사이드바
 * 버튼에는 확인이 없었다(AuthStatusBadge에만 있었는데 그 배지는 개발자 화면 전용).
 */

test("게스트가 로그아웃을 누르면 바로 나가지 않고 무엇을 잃는지 알려준다", async () => {
  await renderApp();

  await userEvent.click(within(sidebar()).getByRole("button", { name: /로그아웃/ }));

  expect(await within(sidebar()).findByRole("alert")).toHaveTextContent("돌아올 수 없어요");
  /* 아직 나가지 않았다 — 관문으로 넘어갔으면 사이드바 자체가 사라진다. */
  expect(within(sidebar()).getByRole("button", { name: "취소" })).toBeInTheDocument();
});

test("확인에서 취소하면 로그아웃하지 않는다", async () => {
  await renderApp();

  await userEvent.click(within(sidebar()).getByRole("button", { name: /로그아웃/ }));
  await userEvent.click(await within(sidebar()).findByRole("button", { name: "취소" }));

  expect(within(sidebar()).queryByRole("alert")).not.toBeInTheDocument();
  expect(within(sidebar()).getByRole("button", { name: /로그아웃/ })).toBeInTheDocument();
});

/* 계정 사용자는 다시 로그인하면 그대로 돌아온다. 되돌릴 수 있는 동작에까지 확인을
   붙이면 확인이라는 신호가 값싸진다. */
test("계정 사용자는 확인 없이 로그아웃된다", async () => {
  setMockSession({
    ...GUEST_SESSION,
    user: { ...GUEST_SESSION.user, is_anonymous: false, email: "trip@example.com" },
  } as typeof GUEST_SESSION);
  await renderApp();

  await userEvent.click(within(sidebar()).getByRole("button", { name: /로그아웃/ }));

  expect(await screen.findByRole("button", { name: "게스트로 시작하기" })).toBeInTheDocument();
});

/* 저장한 일정 목록. (SCHEDULE 카드 2) */

test("저장한 일정이 없으면 그 사실을 알린다", async () => {
  await renderApp();

  expect(within(sidebar()).getByText("아직 저장한 일정이 없어요")).toBeInTheDocument();
});

test("저장한 일정이 목록에 뜨고 누르면 그 일정이 열린다", async () => {
  server.schedules = [
    {
      id: "sched-1",
      title: "종로 반나절",
      session_id: "chat-1",
      created_at: "2026-08-31T14:30:00+09:00",
      updated_at: "2026-08-31T14:30:00+09:00",
    },
  ];

  await renderApp();

  const entry = await within(sidebar()).findByRole("button", { name: /종로 반나절/ });
  await userEvent.click(entry);

  /* 저장한 일정은 SchedulePage가 ?saved=로 받아 연다 — 대화와 다른 화면이다. */
  await waitFor(() => expect(window.location.search).toContain("saved=sched-1"));
});

/* 대화 목록과 별도 저장소다. 세션이 30일 뒤 정리돼도 저장한 일정은 남으므로
   한쪽이 비어도 다른 쪽은 그려져야 한다. */
test("대화가 없어도 저장한 일정은 보인다", async () => {
  server.sessions = [];
  server.schedules = [
    {
      id: "sched-1",
      title: "종로 반나절",
      session_id: null,
      created_at: "2026-08-31T14:30:00+09:00",
      updated_at: "2026-08-31T14:30:00+09:00",
    },
  ];

  render(<App />);
  await screen.findByRole("button", { name: "추천 시작하기" });

  expect(await within(sidebar()).findByText("종로 반나절")).toBeInTheDocument();
  expect(within(sidebar()).getByText("아직 대화 기록이 없어요")).toBeInTheDocument();
});
