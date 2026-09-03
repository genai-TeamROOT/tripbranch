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

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import App from "../../App";
import { resetChatSessionsCache } from "../../state/chatSessions";

const SEED_FAVORITES = [
  { id: "fav-1", label: "회사 (역삼동)" },
  { id: "fav-2", label: "집 (성수동)" },
];

/** 계정에 쌓인 대화. 서버가 주는 모양 그대로다. */
const server = vi.hoisted(() => ({
  sessions: [] as { session_id: string; title: string; place_name: string | null; last_active_at: string }[],
  renamed: [] as { id: string; title: string }[],
  deleted: [] as string[],
  resumed: [] as string[],
  /** 이어서 보낸 발화가 실어 나간 session_id. null이면 새 대화로 간 것이다. */
  chatSessionIds: [] as (string | null)[],
}));

vi.mock("../../api/trip", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/trip")>();
  return {
    ...actual,
    fetchChatSessions: async () => ({ sessions: server.sessions }),
    /* 사이드바는 조회가 아니라 resume을 부른다 — 만료된 대화를 되살려야 이어
       물었을 때 같은 세션에 붙는다. resume의 응답은 항상 resumable: true다. */
    resumeChatSession: async (sessionId: string) => {
      const found = server.sessions.find((item) => item.session_id === sessionId);
      if (!found) throw new Error("없는 대화");
      server.resumed.push(sessionId);
      return {
        session_id: sessionId,
        title: found.title,
        turns: [
          { user_input: "비 오는데 어디 갈까", assistant_message: "실내를 찾아볼게요", intent: "RECOMMEND", place_names: [], at: "2026-09-03T09:00:00+09:00" },
        ],
        /* 추천은 그 턴이 기록되기 전에 남는다(실측 평균 97초 먼저). */
        recommendations: [
          { place_id: "p1", run_id: "run_1", name: "국립중앙박물관", rank: 1, distance_km: 1.2, environment_type: "indoor", reason: null, shown_at: "2026-09-03T08:58:23+09:00" },
        ],
        last_active_at: found.last_active_at,
        resumable: true,
      };
    },
    streamChat: async (request: { session_id: string | null }) => {
      server.chatSessionIds.push(request.session_id);
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
  server.sessions = [
    {
      session_id: "chat-1",
      title: "비 오는 날 아이와 함께 갈 곳",
      place_name: null,
      last_active_at: "2026-09-03T09:00:00+09:00",
    },
    {
      session_id: "chat-2",
      title: "갑자기 뜬 2시간, 카페 추천",
      place_name: "블루보틀 성수",
      last_active_at: "2026-09-02T09:00:00+09:00",
    },
  ];
  server.renamed = [];
  server.deleted = [];
  server.resumed = [];
  server.chatSessionIds = [];
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

test("대화에 언급된 장소가 목록에 함께 보인다", async () => {
  await renderApp();

  expect(within(sidebar()).getByText("블루보틀 성수")).toBeInTheDocument();
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
test("지난 대화를 열면 마지막 부분이라고 밝힌다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));

  expect(await screen.findByText(/마지막 부분이에요/)).toBeInTheDocument();
});

/* 말풍선만 돌려주면 "추천을 받았다"는 사실만 남고 무엇을 받았는지가 사라진다. */
test("지난 대화에 그때 본 장소가 함께 펼쳐진다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(within(sidebar()).getByRole("button", { name: "비 오는 날 아이와 함께 갈 곳 대화 열기" }));

  expect(await screen.findByText("그때 추천받은 곳")).toBeInTheDocument();
  expect(screen.getByText("국립중앙박물관")).toBeInTheDocument();
  /* 저장된 값만 보여준다 — 거리·실내외는 있고 점수·운영시간은 기록이 없다. */
  expect(screen.getByText("1.2km · 실내")).toBeInTheDocument();
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
