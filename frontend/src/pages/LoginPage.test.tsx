/*
 * 역할: 로그인 화면이 실제로 로그인 요청을 보내고, 실패 사유를 구분해서 보여주는지
 *   검증한다.
 * 호출 시점: vitest 실행 시.
 *
 * **실패를 뭉뚱그리지 않는 것이 핵심이다.** 비밀번호가 틀린 것과 이메일 확인이
 * 안 끝난 것은 사용자가 해야 할 일이 완전히 다르다 — 뭉치면 확인 메일을 안 누른
 * 사람이 비밀번호만 계속 다시 친다.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, test } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { LoginPage } from "./LoginPage";
import {
  emailAuthCalls,
  resetSupabaseMock,
  setMockEmailAuthError,
  setMockSession,
} from "../test/supabaseMock";
import { resetSupabaseClient } from "../auth/supabaseClient";

beforeEach(() => {
  localStorage.clear();
  /* 세션이 있으면 화면이 곧바로 리다이렉트한다 — 폼을 보려면 신원이 없어야 한다. */
  setMockSession(null);
});

afterEach(() => {
  resetSupabaseMock();
  resetSupabaseClient();
});

function renderLogin() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<p>홈 화면</p>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

async function fillAndSubmit(email = "trip@example.com", password = "Ab3!xyzw") {
  if (email) await userEvent.type(screen.getByLabelText("이메일"), email);
  if (password) await userEvent.type(screen.getByLabelText("비밀번호"), password);
  await userEvent.click(screen.getByRole("button", { name: "로그인" }));
}

test("이메일과 비밀번호로 로그인하면 홈으로 간다", async () => {
  renderLogin();
  await fillAndSubmit();

  await waitFor(() => expect(emailAuthCalls()).toHaveLength(1));
  const call = emailAuthCalls()[0];
  expect(call.method).toBe("signInWithPassword");
  expect(call.email).toBe("trip@example.com");

  expect(await screen.findByText("홈 화면")).toBeInTheDocument();
});

/* 안 채운 것과 틀린 것은 다른 상태다. 빈 값을 서버로 보내면 invalid_credentials가
   돌아와 "비밀번호가 틀렸나" 싶어진다. */
test("빈 값으로는 요청을 보내지 않는다", async () => {
  renderLogin();

  await userEvent.click(screen.getByRole("button", { name: "로그인" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("모두 입력해주세요");
  expect(emailAuthCalls()).toHaveLength(0);
});

test("비밀번호가 틀리면 그 사유를 보여준다", async () => {
  setMockEmailAuthError({ message: "Invalid login credentials", code: "invalid_credentials" });
  renderLogin();
  await fillAndSubmit();

  expect(await screen.findByRole("alert")).toHaveTextContent("이메일 또는 비밀번호가 맞지 않아요");
  /* 홈으로 넘어가지 않는다. */
  expect(screen.queryByText("홈 화면")).not.toBeInTheDocument();
});

/* 이 파일에서 가장 중요한 테스트다. */
test("이메일 확인이 안 끝난 계정은 메일을 누르라고 안내한다", async () => {
  setMockEmailAuthError({ message: "Email not confirmed", code: "email_not_confirmed" });
  renderLogin();
  await fillAndSubmit();

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("이메일 확인");
  expect(alert).toHaveTextContent("링크");
  /* 비밀번호 문제로 읽히면 안 된다. */
  expect(alert).not.toHaveTextContent("비밀번호가 맞지 않");
});

test("게스트 시작은 그대로 동작한다", async () => {
  renderLogin();

  await userEvent.click(screen.getByRole("button", { name: "게스트로 시작하기" }));

  expect(await screen.findByText("홈 화면")).toBeInTheDocument();
  /* 게스트 경로는 이메일 인증을 거치지 않는다. */
  expect(emailAuthCalls()).toHaveLength(0);
});

test("이미 로그인돼 있으면 폼을 보여주지 않는다", async () => {
  resetSupabaseMock(); // 기본값이 게스트 세션 있음
  renderLogin();

  expect(await screen.findByText("홈 화면")).toBeInTheDocument();
  expect(screen.queryByLabelText("이메일")).not.toBeInTheDocument();
});
