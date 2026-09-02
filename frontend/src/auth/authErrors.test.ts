/*
 * 역할: Supabase auth 오류가 한국어 문구로 바뀌는지, 그리고 **계정 존재 여부를
 *   흘리지 않는지** 검증한다.
 * 호출 시점: vitest 실행 시.
 */

import { expect, test } from "vitest";
import { authErrorMessage } from "./authErrors";

test("code로 문구를 고른다", () => {
  expect(authErrorMessage({ code: "invalid_credentials" })).toBe(
    "이메일 또는 비밀번호가 맞지 않아요.",
  );
  expect(authErrorMessage({ code: "email_not_confirmed" })).toContain("이메일 확인");
});

/* Supabase가 code를 안 채우는 경로가 남아 있다. message만 와도 문구가 나와야 한다. */
test("code가 없으면 message 원문으로 맞춘다", () => {
  expect(authErrorMessage({ message: "Invalid login credentials" })).toBe(
    "이메일 또는 비밀번호가 맞지 않아요.",
  );
  expect(authErrorMessage({ message: "Password should be at least 8 characters" })).toContain(
    "비밀번호가 너무 쉬워요",
  );
});

test("429는 code가 없어도 요청 과다로 읽는다", () => {
  expect(authErrorMessage({ status: 429, message: "..." })).toContain("잠시 후");
});

test("모르는 오류는 원문을 노출하지 않는다", () => {
  const message = authErrorMessage({ message: "some internal detail leaked here" });
  expect(message).not.toContain("internal");
  expect(message).toBe("요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.");
});

test("오류가 없어도 빈 문자열을 내지 않는다", () => {
  expect(authErrorMessage(null)).toBeTruthy();
  expect(authErrorMessage(undefined)).toBeTruthy();
});

/*
 * 이 파일에서 가장 중요한 테스트다. "가입되지 않은 이메일이에요" 같은 문구를
 * 만들면 주소를 하나씩 넣어 가입 여부를 캐낼 수 있다(계정 열거). Supabase가
 * 로그인 실패를 하나로 뭉쳐 주는 보호를 우리가 풀지 않는지 고정한다.
 */
test("계정이 있는지 없는지 알려주는 문구를 만들지 않는다", () => {
  const 흘리는_표현 = [/가입되지 않/, /없는 이메일/, /등록되지 않/, /이미 가입/, /존재하지 않/];
  const 모든_입력 = [
    { code: "invalid_credentials" },
    { code: "email_not_confirmed" },
    { code: "weak_password" },
    { code: "validation_failed" },
    { message: "Invalid login credentials" },
    { message: "User already registered" },
    { message: "무엇인지 모를 오류" },
    { status: 429 },
    null,
  ];

  for (const input of 모든_입력) {
    const message = authErrorMessage(input);
    for (const pattern of 흘리는_표현) {
      expect(message).not.toMatch(pattern);
    }
  }
});
