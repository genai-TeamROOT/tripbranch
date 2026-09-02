/*
 * 역할: 사이드바(셸 + SideDrawerContent)의 동작을 앱 통합 수준에서 검증한다.
 * 입력: 렌더된 App, 사용자 클릭·입력.
 * 출력: 즐겨찾기·채팅 히스토리 편집, 접힘 전환, 라우트 이동에 대한 assertion.
 * 호출 시점: vitest 실행 시.
 *
 * 즐겨찾기와 채팅 히스토리는 아직 백엔드가 없는 localStorage 목업이다
 * (state/sidebarStorage.ts). 여기서 검증하는 것은 "화면이 목록을 제대로
 * 편집하고 보존하는가"까지다.
 *
 * 예전에는 화면이 기본 예시 항목을 들고 있어 그대로 눌러볼 수 있었는데, 지금은
 * 빈 목록에서 시작한다. 그래서 테스트가 localStorage에 직접 씨앗을 심는다 —
 * 저장 키가 바뀌면 여기도 같이 깨지므로 sidebarStorage.ts와 짝으로 본다.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import App from "../../App";

const SEED_FAVORITES = [
  { id: "fav-1", label: "회사 (역삼동)" },
  { id: "fav-2", label: "집 (성수동)" },
];
const SEED_HISTORY = [
  { id: "chat-1", label: "비 오는 날 아이와 함께 갈 곳" },
  { id: "chat-2", label: "갑자기 뜬 2시간, 카페 추천" },
];

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  localStorage.setItem("tb_favorites", JSON.stringify(SEED_FAVORITES));
  localStorage.setItem("tb_chat_history", JSON.stringify(SEED_HISTORY));
  window.history.pushState({}, "", "/");
});

/*
 * 렌더 직후에는 게스트 세션 조회가 끝나지 않아 관문(RequireUser)이 로딩 문구만
 * 그린다. 셸이 붙을 때까지 기다린 뒤에 사이드바를 만진다(App.test.tsx와 같은 이유).
 */
async function renderApp() {
  render(<App />);
  await screen.findByRole("button", { name: "추천 시작하기" });
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
