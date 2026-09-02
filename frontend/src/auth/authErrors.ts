/*
 * 역할: Supabase auth 오류를 사용자에게 보여줄 한국어 문구로 바꾼다.
 * 입력: signUp/signInWithPassword/resetPasswordForEmail이 돌려준 오류.
 * 출력: 화면에 그대로 띄울 한 문장.
 * 호출 시점: AuthContext의 인증 함수들이 오류를 던지기 직전에 호출한다.
 *
 * 세 화면(로그인·회원가입·비밀번호 재설정)이 같은 문구를 써야 해서 한곳에 모은다.
 * Supabase 원문은 영어이고, 그대로 띄우면 "Invalid login credentials" 같은 문장이
 * 화면에 나온다.
 *
 * **아이디 존재 여부를 알려주는 문구를 만들지 않는다.** "가입되지 않은 이메일이에요"
 * 같은 문장은 친절해 보이지만, 이메일을 하나씩 넣어 보면 어떤 주소가 가입돼 있는지
 * 알아낼 수 있는 통로가 된다(계정 열거). Supabase가 로그인 실패를 이메일·비밀번호
 * 구분 없이 하나로 뭉쳐 돌려주는 것도 같은 이유다 — 그 뭉침을 여기서 풀지 않는다.
 */

/** Supabase 오류에서 우리가 실제로 읽는 부분만. AuthError 전체를 끌고 오지 않는다. */
export interface SupabaseAuthErrorLike {
  message?: string;
  code?: string;
  status?: number;
}

const FALLBACK = "요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.";

/*
 * code로 먼저 맞춰 본다. Supabase가 code를 안 채우는 경로가 남아 있어서
 * message 조각까지 함께 본다 — code만 보면 조용히 FALLBACK으로 새어 나간다.
 */
const BY_CODE: Record<string, string> = {
  invalid_credentials: "이메일 또는 비밀번호가 맞지 않아요.",
  email_not_confirmed: "아직 이메일 확인이 끝나지 않았어요. 받은 메일의 링크를 눌러주세요.",
  weak_password: "비밀번호가 너무 쉬워요. 8자 이상으로, 다른 곳에서 쓰지 않는 값으로 정해주세요.",
  over_email_send_rate_limit: "메일을 너무 자주 보냈어요. 잠시 후에 다시 시도해주세요.",
  over_request_rate_limit: "요청이 너무 잦아요. 잠시 후에 다시 시도해주세요.",
  validation_failed: "입력한 값을 다시 확인해주세요.",
  email_address_invalid: "이메일 형식이 올바르지 않아요.",
  signup_disabled: "지금은 회원가입을 받고 있지 않아요.",
  email_provider_disabled: "지금은 이메일로 가입할 수 없어요.",
  same_password: "지금 쓰고 있는 비밀번호와 달라야 해요.",
};

/* message 원문 조각 → 문구. code가 비어 있을 때만 쓴다. */
const BY_MESSAGE: Array<[RegExp, string]> = [
  [/invalid login credentials/i, BY_CODE.invalid_credentials],
  [/email not confirmed/i, BY_CODE.email_not_confirmed],
  [/password should be at least/i, BY_CODE.weak_password],
  [/rate limit|too many requests/i, BY_CODE.over_request_rate_limit],
  [/unable to validate email|invalid format/i, BY_CODE.email_address_invalid],
  [/signups not allowed|signup is disabled/i, BY_CODE.signup_disabled],
];

export function authErrorMessage(error: SupabaseAuthErrorLike | null | undefined): string {
  if (!error) return FALLBACK;

  if (error.code && BY_CODE[error.code]) return BY_CODE[error.code];

  const message = error.message ?? "";
  for (const [pattern, text] of BY_MESSAGE) {
    if (pattern.test(message)) return text;
  }

  /* 429는 code가 없어도 의미가 분명하다. */
  if (error.status === 429) return BY_CODE.over_request_rate_limit;

  return FALLBACK;
}
