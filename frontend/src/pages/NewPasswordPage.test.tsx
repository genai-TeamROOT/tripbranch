/*
 * 역할: 재설정 링크로 돌아온 화면이 세션 유무를 먼저 가르는지, 새 비밀번호를
 *   실제로 저장하는지 검증한다.
 * 호출 시점: vitest 실행 시.
 *
 * **세션이 없으면 폼을 보여주지 않는 것이 핵심이다.** 링크 없이 들어왔거나 링크가
 * 만료된 경우인데, 폼을 띄우고 제출 시점에 실패시키면 사용자는 비밀번호를 다
 * 입력한 뒤에야 헛수고였음을 안다.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, test } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { NewPasswordPage } from "./NewPasswordPage";
import {
  emailAuthCalls,
  resetSupabaseMock,
  setMockEmailAuthError,
  setMockSession,
} from "../test/supabaseMock";
import { resetSupabaseClient } from "../auth/supabaseClient";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  resetSupabaseMock();
  resetSupabaseClient();
});

function renderPage() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/reset-password/new"]}>
        <Routes>
          <Route path="/reset-password/new" element={<NewPasswordPage />} />
          <Route path="/" element={<p>홈 화면</p>} />
          <Route path="/reset-password" element={<p>재설정 요청 화면</p>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

async function fill(password: string, confirm = password) {
  await userEvent.type(await screen.findByLabelText("새 비밀번호"), password);
  await userEvent.type(screen.getByLabelText("새 비밀번호 확인"), confirm);
  await userEvent.click(screen.getByRole("button", { name: "비밀번호 바꾸기" }));
}

/* 이 파일에서 가장 중요한 테스트다. */
test("링크 없이 들어오면 폼 대신 만료 안내를 보여준다", async () => {
  setMockSession(null);
  renderPage();

  expect(await screen.findByText(/링크가 만료되었거나/)).toBeInTheDocument();
  expect(screen.queryByLabelText("새 비밀번호")).not.toBeInTheDocument();
});

test("만료 안내에서 재설정 요청 화면으로 돌아갈 수 있다", async () => {
  setMockSession(null);
  renderPage();

  await userEvent.click(await screen.findByRole("button", { name: "재설정 링크 다시 받기" }));

  expect(await screen.findByText("재설정 요청 화면")).toBeInTheDocument();
});

test("새 비밀번호를 저장하고 홈으로 간다", async () => {
  renderPage(); // mock 기본값이 세션 있음 — 링크로 세션이 선 상태다
  await fill("Ab3!xyzw");

  await waitFor(() => expect(emailAuthCalls()).toHaveLength(1));
  const call = emailAuthCalls()[0];
  expect(call.method).toBe("updateUser");
  expect(call.password).toBe("Ab3!xyzw");

  expect(await screen.findByText("홈 화면")).toBeInTheDocument();
});

test("두 번 입력한 비밀번호가 다르면 요청을 보내지 않는다", async () => {
  renderPage();
  await fill("Ab3!xyzw", "Ab3!xyzz");

  expect(await screen.findByRole("alert")).toHaveTextContent("서로 달라요");
  expect(emailAuthCalls()).toHaveLength(0);
});

/* 정책 위반은 가입 화면과 같은 문구로 나와야 한다 — 두 화면이 다른 말을 하면 안 된다. */
test("서버가 거부한 비밀번호 사유를 그대로 보여준다", async () => {
  setMockEmailAuthError({ message: "weak", code: "weak_password" });
  renderPage();
  await fill("Ab3!xyzw");

  expect(await screen.findByRole("alert")).toHaveTextContent("비밀번호");
  expect(screen.queryByText("홈 화면")).not.toBeInTheDocument();
});

test("회원가입 화면과 같은 비밀번호 조건을 안내한다", async () => {
  renderPage();

  expect(
    await screen.findByText("8자 이상, 대문자·소문자·숫자·기호를 각각 하나 이상 넣어주세요."),
  ).toBeInTheDocument();
});
