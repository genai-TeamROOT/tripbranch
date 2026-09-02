/*
 * 역할: 모바일 푸시 드로어가 햄버거로 열리고, 본문 탭·내비게이션으로 닫히는지 검증한다.
 * 입력: 렌더된 App, 사용자 클릭.
 * 출력: aria-hidden/inert 토글과 닫힘 경로 두 가지에 대한 assertion.
 *
 * 이 드로어는 오버레이가 아니라 "푸시" 드로어다 — 항상 DOM에 있고 본문(.tb-shell)이
 * 오른쪽으로 밀려나며 드러난다. 그래서 닫기 ✕ 버튼이 따로 없고, 밀려난 본문을
 * 누르면 닫힌다(AppShell의 onClickCapture). 열림 여부는 DOM 존재가 아니라
 * aria-hidden/inert로만 드러나므로 그 속성으로 판정한다.
 *
 * jsdom은 미디어쿼리(md:hidden)를 적용하지 않아 데스크톱 사이드바와 모바일
 * 드로어가 항상 함께 DOM에 있다. 드로어 쪽은 aria-hidden 속성을 가진 루트로,
 * 데스크톱 사이드바(role=complementary)와 구분해서 찾는다.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import App from "../../App";

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  window.history.pushState({}, "", "/");
});

async function renderApp() {
  render(<App />);
  await screen.findByRole("button", { name: "추천 시작하기" });
}

/*
 * 드로어 루트는 SideDrawer가 그리는 유일한 [aria-hidden] 컨테이너다. 브랜드 표기를
 * 품고 있어 그것을 기준으로 거슬러 올라간다 — 클래스명에 기대지 않는다.
 */
function drawerRoot(): HTMLElement {
  const brands = screen.getAllByText("TripBranch");
  for (const brand of brands) {
    const root = brand.closest("[aria-hidden]");
    if (root) return root as HTMLElement;
  }
  throw new Error("드로어 루트를 찾지 못했다");
}

/** 밀려나는 본문 컨테이너(.tb-shell). 탭-투-클로즈 핸들러가 여기 붙는다. */
function shell(): HTMLElement {
  const node = document.querySelector(".tb-shell");
  if (!node) throw new Error("본문 셸을 찾지 못했다");
  return node as HTMLElement;
}

test("처음에는 드로어가 aria-hidden·inert 상태다", async () => {
  await renderApp();

  const root = drawerRoot();
  expect(root).toHaveAttribute("aria-hidden", "true");
  expect(root).toHaveAttribute("inert");
});

test("햄버거를 누르면 드로어가 열린다", async () => {
  const user = userEvent.setup();
  await renderApp();

  await user.click(screen.getByRole("button", { name: "메뉴 열기" }));

  const root = drawerRoot();
  expect(root).toHaveAttribute("aria-hidden", "false");
  expect(root).not.toHaveAttribute("inert");
});

/*
 * 이 드로어에는 닫기 ✕ 버튼이 없다. 밀려난 본문을 누르는 것이 유일한
 * "취소하고 돌아가기" 경로라, 이게 깨지면 모바일에서 드로어에 갇힌다.
 */
test("밀려난 본문을 누르면 드로어가 닫힌다", async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(screen.getByRole("button", { name: "메뉴 열기" }));
  expect(drawerRoot()).toHaveAttribute("aria-hidden", "false");

  /*
   * "추천 시작하기"는 입력이 비면 disabled라 클릭 이벤트가 아예 나지 않는다 —
   * 탭-투-클로즈를 확인하려면 활성 요소를 눌러야 한다. 컴포저 입력칸은 항상 활성이고
   * 누른다고 다른 일이 일어나지도 않는다.
   */
  await user.click(within(shell()).getByRole("textbox"));

  expect(drawerRoot()).toHaveAttribute("aria-hidden", "true");
});

test("드로어 안에서 메뉴를 누르면 이동하면서 닫힌다", async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(screen.getByRole("button", { name: "메뉴 열기" }));

  const root = drawerRoot();
  const { getByRole } = within(root);
  await user.click(getByRole("button", { name: "취향 설정" }));

  expect(screen.getByText(/끌리시나요/)).toBeInTheDocument();
  expect(drawerRoot()).toHaveAttribute("aria-hidden", "true");
});
