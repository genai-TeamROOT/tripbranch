/*
 * 역할: 테스트에서 Supabase auth를 대신하는 인메모리 가짜 클라이언트.
 * 입력: setMockSession/setMockSignInError로 지정한 세션·오류 상태.
 * 출력: createClient 대체 함수와 상태 제어 헬퍼.
 * 호출 시점: src/test/setup.ts가 @supabase/supabase-js를 이 모듈로 mock할 때 로드된다.
 * TODO: 정식 로그인 경로가 생기면 linkIdentity/updateUser도 여기에 추가한다.
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

export function setMockSession(session: Session | null): void {
  currentSession = session;
  listeners.forEach((listener) => listener("SIGNED_IN", session));
}

export function setMockSignInError(message: string | null): void {
  signInError = message;
}

export function resetSupabaseMock(): void {
  currentSession = GUEST_SESSION;
  signInError = null;
  listeners = [];
}

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
