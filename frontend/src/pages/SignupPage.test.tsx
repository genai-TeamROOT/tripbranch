/*
 * 역할: 회원가입 화면이 실제로 가입 요청을 보내는지, 그리고 **가입 직후 로그인된
 *   것처럼 굴지 않는지** 검증한다.
 * 호출 시점: vitest 실행 시.
 *
 * 이메일 확인이 켜져 있어 signUp은 세션을 주지 않는다. 화면이 그 사실을 지키는지가
 * 이 파일의 핵심이다 — 홈으로 보내 버리면 사용자는 메일을 확인하지 않고 떠난다.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { SignupPage } from "./SignupPage";
import {
  emailAuthCalls,
  resetSupabaseMock,
  setMockEmailAuthError,
  setMockSession,
} from "../test/supabaseMock";
import { resetSupabaseClient } from "../auth/supabaseClient";

beforeEach(() => {
  localStorage.clear();
  /* 이 화면은 세션과 무관하다 — 관문에서 처음부터 가입하는 경로다. */
  setMockSession(null);
});

afterEach(() => {
  resetSupabaseMock();
  resetSupabaseClient();
});

function renderSignup() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/signup"]}>
        <SignupPage />
      </MemoryRouter>
    </AuthProvider>,
  );
}

async function fill(overrides?: Partial<Record<"이름" | "이메일" | "비밀번호" | "확인", string>>) {
  const values = {
    이름: "나종원",
    이메일: "trip@example.com",
    비밀번호: "Ab3!xyzw",
    확인: "Ab3!xyzw",
    ...overrides,
  };
  await userEvent.type(screen.getByLabelText("이름"), values.이름);
  await userEvent.type(screen.getByLabelText("이메일"), values.이메일);
  await userEvent.type(screen.getByLabelText("비밀번호"), values.비밀번호);
  await userEvent.type(screen.getByLabelText("비밀번호 확인"), values.확인);
  await userEvent.click(screen.getByRole("checkbox"));
}

test("약관에 동의하기 전에는 제출할 수 없다", async () => {
  renderSignup();

  expect(screen.getByRole("button", { name: "가입하고 시작하기" })).toBeDisabled();

  await userEvent.click(screen.getByRole("checkbox"));

  expect(screen.getByRole("button", { name: "가입하고 시작하기" })).toBeEnabled();
});

test("가입하면 이름·이메일·비밀번호가 그대로 나간다", async () => {
  renderSignup();
  await fill();

  await userEvent.click(screen.getByRole("button", { name: "가입하고 시작하기" }));

  await waitFor(() => expect(emailAuthCalls()).toHaveLength(1));
  const call = emailAuthCalls()[0];
  expect(call.method).toBe("signUp");
  expect(call.email).toBe("trip@example.com");
  expect(call.password).toBe("Ab3!xyzw");
  /* 이름은 user_metadata.name으로 간다 — identityLabel이 그 값을 읽는다. */
  expect(call.name).toBe("나종원");
});

/* 이 파일에서 가장 중요한 테스트다. */
test("가입 직후 로그인된 것처럼 굴지 않고 메일 확인을 안내한다", async () => {
  renderSignup();
  await fill();

  await userEvent.click(screen.getByRole("button", { name: "가입하고 시작하기" }));

  expect(await screen.findByText(/확인 메일을 보냈어요/)).toBeInTheDocument();
  expect(screen.getByText("trip@example.com")).toBeInTheDocument();
  /* 폼이 남아 있으면 다시 눌러 확인 메일이 또 나간다(발송 한도). */
  expect(screen.queryByRole("button", { name: "가입하고 시작하기" })).not.toBeInTheDocument();
});

test("두 번 입력한 비밀번호가 다르면 요청을 보내지 않는다", async () => {
  renderSignup();
  await fill({ 확인: "Ab3!xyzz" });

  await userEvent.click(screen.getByRole("button", { name: "가입하고 시작하기" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("서로 달라요");
  expect(emailAuthCalls()).toHaveLength(0);
});

test("이름이 비어 있으면 요청을 보내지 않는다", async () => {
  renderSignup();
  await fill({ 이름: " " });

  await userEvent.click(screen.getByRole("button", { name: "가입하고 시작하기" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("이름을 입력해주세요");
  expect(emailAuthCalls()).toHaveLength(0);
});

/*
 * 길이·문자 종류·유출 여부는 화면이 아니라 Supabase 정책이 정본이다. 화면에서 또
 * 검사하면 대시보드 설정을 바꾸는 순간 두 곳이 갈린다 — 서버 판정을 그대로 보여준다.
 */
test("서버가 거부한 비밀번호 사유를 그대로 보여준다", async () => {
  setMockEmailAuthError({ message: "weak", code: "weak_password" });
  renderSignup();
  await fill();

  await userEvent.click(screen.getByRole("button", { name: "가입하고 시작하기" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("비밀번호");
  /* 요청은 실제로 나갔다 — 화면이 미리 막은 게 아니다. */
  expect(emailAuthCalls()).toHaveLength(1);
});

test("약관 보기는 아직 갈 곳이 없다고 밝힌다", async () => {
  renderSignup();

  await userEvent.click(screen.getByRole("button", { name: "보기" }));

  expect(await screen.findByText(/약관 전문은 아직 준비 중/)).toBeInTheDocument();
});
