/*
 * 역할: 게스트 로그인 관문(D-062)의 라우팅과 실패 표시를 검증한다.
 * 입력: mock Supabase auth 상태, 버튼 클릭.
 * 출력: 리다이렉트·게스트 발급·설정 오류 표시에 대한 assertion.
 * 호출 시점: vitest 실행 시 인증 회귀 테스트로 호출된다.
 * TODO: 정식 로그인이 들어오면 계정 연결(linkIdentity) 경로도 여기서 검증한다.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { GUEST_SESSION, setMockSession, setMockSignInError } from "../test/supabaseMock";
import { resetSupabaseClient } from "./supabaseClient";

/* 데스크톱 사이드바(항상 렌더)와 모바일 드로어가 같은 SideDrawerContent를 각자
   렌더하므로, 신원 라벨 같은 공통 텍스트를 screen에서 그냥 찾으면 두 곳 모두
   걸려 "여러 개 발견" 에러가 난다 — 데스크톱 사이드바(<aside>, role=complementary)
   안으로 좁혀서 찾는다. */
function sidebar() {
  return screen.getByRole("complementary");
}

beforeEach(() => {
  window.history.pushState({}, "", "/");
  sessionStorage.clear();
});

afterEach(() => {
  resetSupabaseClient();
});

test("신원이 없으면 홈 대신 로그인 관문을 보여준다", async () => {
  setMockSession(null);

  render(<App />);

  expect(await screen.findByRole("button", { name: "게스트로 시작하기" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "추천 시작하기" })).not.toBeInTheDocument();
});

test("게스트로 시작하면 원래 가려던 화면으로 들어간다", async () => {
  setMockSession(null);

  render(<App />);

  await userEvent.click(await screen.findByRole("button", { name: "게스트로 시작하기" }));

  expect(await screen.findByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
});

test("게스트 발급이 실패하면 화면에 사유를 남기고 관문에 머문다", async () => {
  setMockSession(null);
  setMockSignInError("anonymous_provider_disabled");

  render(<App />);

  await userEvent.click(await screen.findByRole("button", { name: "게스트로 시작하기" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("anonymous_provider_disabled");
  expect(screen.getByRole("button", { name: "게스트로 시작하기" })).toBeInTheDocument();
});

test("이미 신원이 있으면 관문을 거치지 않고 홈으로 간다", async () => {
  render(<App />);

  expect(await screen.findByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "게스트로 시작하기" })).not.toBeInTheDocument();
});

test("게스트로 들어오면 사이드바에 게스트 상태가 표시된다", async () => {
  setMockSession(null);

  render(<App />);

  await userEvent.click(await screen.findByRole("button", { name: "게스트로 시작하기" }));

  expect(await within(sidebar()).findByText("게스트로 이용 중")).toBeInTheDocument();
});

/* 계정 연결 후에는 같은 uid로 is_anonymous만 false가 된다(D-062 2절).
   표시 분기가 그 전환을 따라가는지 고정한다. */
test("계정으로 승격되면 게스트 표시가 사라진다", async () => {
  setMockSession({
    ...GUEST_SESSION,
    user: { ...GUEST_SESSION.user, is_anonymous: false, email: "trip@example.com" },
  } as typeof GUEST_SESSION);

  render(<App />);
  await screen.findByRole("button", { name: "추천 시작하기" });

  expect(within(sidebar()).getByText("trip@example.com")).toBeInTheDocument();
  expect(within(sidebar()).queryByText("게스트로 이용 중")).not.toBeInTheDocument();
});

/* 계정 메뉴(게스트 라벨 클릭 → 확인 → 해제, Esc 취소)는 이 라벨을 쓰는
   AuthStatusBadge 자체의 동작이라 AuthStatusBadge.test.tsx로 옮겼다 — 사이드바
   쪽은 클릭할 수 없는 순수 라벨이고(로그아웃 버튼과 나란히 있어 배지 드롭다운까지
   열리면 "로그아웃"이 두 개로 보인다), 배지 자체는 사이드바가 없는
   DeveloperChatPage에서만 쓰인다. */

/* 조용한 통과 금지(D-042와 같은 방향). 설정이 없을 때 "비로그인 상태"로 넘어가면
   프론트가 토큰 없이 도는 걸 아무도 모른 채 계속 쓰게 된다. */
test("Supabase 설정이 없으면 통과시키지 않고 설정 오류를 드러낸다", async () => {
  resetSupabaseClient();
  vi.stubEnv("VITE_SUPABASE_URL", "");

  render(<App />);

  expect(await screen.findByText(/인증 설정이 없어요/)).toBeInTheDocument();
  expect(screen.getByText(/VITE_SUPABASE_URL/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "추천 시작하기" })).not.toBeInTheDocument();

  vi.stubEnv("VITE_SUPABASE_URL", "https://test.supabase.co");
});
