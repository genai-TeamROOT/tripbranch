/*
 * 역할: 테스트에서 Supabase auth를 대신하는 인메모리 가짜 클라이언트.
 * 입력: setMockSession/setMockSignInError로 지정한 세션·오류 상태.
 * 출력: createClient 대체 함수와 상태 제어 헬퍼.
 * 호출 시점: src/test/setup.ts가 @supabase/supabase-js를 이 모듈로 mock할 때 로드된다.
 * TODO: 게스트→계정 승계(2차)가 들어오면 updateUser/linkIdentity도 여기에 추가한다.
 */

import type { Session, SupabaseClient } from "@supabase/supabase-js";

/* 기본값을 "게스트 세션이 이미 있는 상태"로 둔다. 로그인 관문이 생기기 전에
   작성된 기존 통합 테스트가 그대로 홈에서 시작할 수 있어야 하기 때문이다. */
export const GUEST_SESSION = {
  access_token: "test_access_token",
  refresh_token: "test_refresh_token",
  expires_in: 3600,
  token_type: "bearer",
  user: {
    id: "00000000-0000-0000-0000-000000000001",
    is_anonymous: true,
    aud: "authenticated",
    app_metadata: {},
    user_metadata: {},
    created_at: "2026-08-19T00:00:00.000Z",
  },
} as unknown as Session;

type AuthListener = (event: string, session: Session | null) => void;

let currentSession: Session | null = GUEST_SESSION;
let signInError: string | null = null;
let listeners: AuthListener[] = [];

/* 이메일 인증 호출을 기록한다. 이메일 확인이 켜져 있어 signUp은 세션을 만들지
   않으므로, 세션 상태만 봐서는 "가입 요청이 나갔는지"를 알 수 없다. */
interface AuthCall {
  method: "signUp" | "signInWithPassword" | "resetPasswordForEmail";
  email: string;
  password?: string;
  name?: string;
  redirectTo?: string;
}
let authCalls: AuthCall[] = [];
let emailAuthError: { message: string; code?: string } | null = null;

export function setMockSession(session: Session | null): void {
  currentSession = session;
  listeners.forEach((listener) => listener("SIGNED_IN", session));
}

export function setMockSignInError(message: string | null): void {
  signInError = message;
}

/** 다음 이메일 인증 호출이 낼 오류. authErrors의 code 매핑을 태우려면 code를 준다. */
export function setMockEmailAuthError(error: { message: string; code?: string } | null): void {
  emailAuthError = error;
}

/** 지금까지 나간 이메일 인증 호출. resetSupabaseMock()이 비운다. */
export function emailAuthCalls(): readonly AuthCall[] {
  return authCalls;
}

export function resetSupabaseMock(): void {
  currentSession = GUEST_SESSION;
  signInError = null;
  listeners = [];
  authCalls = [];
  emailAuthError = null;
}

/* 이메일 확인이 켜져 있을 때 실제 Supabase가 돌려주는 모양이다 — user는 있고
   session은 null이다. 이걸 틀리게 흉내 내면 "가입하자마자 로그인됨"이라는
   존재하지 않는 흐름을 테스트가 통과시킨다. */
const CONFIRMATION_PENDING = { user: { id: "pending", identities: [] }, session: null };

export function createMockSupabaseClient(): SupabaseClient {
  return {
    auth: {
      getSession: async () => ({ data: { session: currentSession }, error: null }),
      onAuthStateChange: (listener: AuthListener) => {
        listeners.push(listener);
        return {
          data: {
            subscription: {
              unsubscribe: () => {
                listeners = listeners.filter((entry) => entry !== listener);
              },
            },
          },
        };
      },
      signOut: async () => {
        currentSession = null;
        listeners.forEach((listener) => listener("SIGNED_OUT", null));
        return { error: null };
      },
      signUp: async (input: {
        email: string;
        password: string;
        options?: { data?: { name?: string }; emailRedirectTo?: string };
      }) => {
        authCalls.push({
          method: "signUp",
          email: input.email,
          password: input.password,
          name: input.options?.data?.name,
          redirectTo: input.options?.emailRedirectTo,
        });
        if (emailAuthError) return { data: { user: null, session: null }, error: emailAuthError };
        return { data: CONFIRMATION_PENDING, error: null };
      },
      signInWithPassword: async (input: { email: string; password: string }) => {
        authCalls.push({
          method: "signInWithPassword",
          email: input.email,
          password: input.password,
        });
        if (emailAuthError) return { data: { user: null, session: null }, error: emailAuthError };
        const account = {
          ...GUEST_SESSION,
          user: { ...GUEST_SESSION.user, is_anonymous: false, email: input.email },
        } as Session;
        currentSession = account;
        listeners.forEach((listener) => listener("SIGNED_IN", account));
        return { data: { session: account, user: account.user }, error: null };
      },
      resetPasswordForEmail: async (email: string, options?: { redirectTo?: string }) => {
        authCalls.push({ method: "resetPasswordForEmail", email, redirectTo: options?.redirectTo });
        if (emailAuthError) return { data: null, error: emailAuthError };
        return { data: {}, error: null };
      },
      signInAnonymously: async () => {
        if (signInError) {
          return { data: { session: null, user: null }, error: { message: signInError } };
        }
        currentSession = GUEST_SESSION;
        listeners.forEach((listener) => listener("SIGNED_IN", currentSession));
        return { data: { session: currentSession, user: GUEST_SESSION.user }, error: null };
      },
    },
  } as unknown as SupabaseClient;
}
