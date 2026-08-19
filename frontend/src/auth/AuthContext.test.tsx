/*
 * 역할: 게스트 로그인 관문(D-062)의 라우팅과 실패 표시를 검증한다.
 * 입력: mock Supabase auth 상태, 버튼 클릭.
 * 출력: 리다이렉트·게스트 발급·설정 오류 표시에 대한 assertion.
 * 호출 시점: vitest 실행 시 인증 회귀 테스트로 호출된다.
 * TODO: 정식 로그인이 들어오면 계정 연결(linkIdentity) 경로도 여기서 검증한다.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { GUEST_SESSION, setMockSession, setMockSignInError } from "../test/supabaseMock";
import { resetSupabaseClient } from "./supabaseClient";

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

test("게스트로 들어오면 홈에 게스트 상태가 표시된다", async () => {
  setMockSession(null);

  render(<App />);

  await userEvent.click(await screen.findByRole("button", { name: "게스트로 시작하기" }));

  expect(await screen.findByText("게스트로 이용 중")).toBeInTheDocument();
});

/* 계정 연결 후에는 같은 uid로 is_anonymous만 false가 된다(D-062 2절).
   표시 분기가 그 전환을 따라가는지 고정한다. */
test("계정으로 승격되면 게스트 표시가 사라진다", async () => {
  setMockSession({
    ...GUEST_SESSION,
    user: { ...GUEST_SESSION.user, is_anonymous: false, email: "trip@example.com" },
  } as typeof GUEST_SESSION);

  render(<App />);

  expect(await screen.findByText("trip@example.com")).toBeInTheDocument();
  expect(screen.queryByText("게스트로 이용 중")).not.toBeInTheDocument();
});

test("배지를 누르면 계정 메뉴가 열리고 한 번 더 확인해야 해제된다", async () => {
  render(<App />);

  await userEvent.click(await screen.findByRole("button", { name: "게스트로 이용 중" }));
  expect(screen.getByRole("menu")).toBeInTheDocument();

  /* 한 번 누른 것만으로는 해제되지 않는다 — 확인 단계가 남아 있다. */
  await userEvent.click(screen.getByRole("button", { name: "세션 해제" }));
  expect(screen.getByText(/돌아올 수 없어요/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "추천 시작하기" })).toBeInTheDocument();
});

test("해제를 확인하면 관문으로 돌아간다", async () => {
  render(<App />);

  await userEvent.click(await screen.findByRole("button", { name: "게스트로 이용 중" }));
  await userEvent.click(screen.getByRole("button", { name: "세션 해제" }));
  await userEvent.click(screen.getByRole("button", { name: "해제" }));

  expect(await screen.findByRole("button", { name: "게스트로 시작하기" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "추천 시작하기" })).not.toBeInTheDocument();
});

test("메뉴는 Esc로 닫히고 확인 단계도 함께 되돌아간다", async () => {
  render(<App />);

  await userEvent.click(await screen.findByRole("button", { name: "게스트로 이용 중" }));
  await userEvent.click(screen.getByRole("button", { name: "세션 해제" }));
  await userEvent.keyboard("{Escape}");

  expect(screen.queryByRole("menu")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "게스트로 이용 중" }));
  expect(screen.getByRole("button", { name: "세션 해제" })).toBeInTheDocument();
  expect(screen.queryByText(/돌아올 수 없어요/)).not.toBeInTheDocument();
});

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
