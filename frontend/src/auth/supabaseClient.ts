/*
 * 역할: 게스트 신원 발급에 쓰는 Supabase 클라이언트를 지연 생성한다.
 * 입력: VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY 환경변수.
 * 출력: SupabaseClient 싱글턴 또는 SupabaseConfigError.
 * 호출 시점: AuthProvider가 세션을 확인하거나 게스트 로그인을 요청할 때 호출된다.
 * TODO: 정식 로그인(D-062 Phase 5)이 들어오면 소셜 provider 연동도 이 클라이언트를 쓴다.
 */

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/* 설정 누락을 "로그인 안 된 상태"와 구분하기 위한 전용 오류. AuthProvider가 이걸
   보고 화면에 설정 오류를 드러낸다 — 조용히 비로그인으로 넘기지 않는다(D-042). */
export class SupabaseConfigError extends Error {
  constructor(public readonly missing: string[]) {
    super(`Supabase 설정이 없어요: ${missing.join(", ")}`);
    this.name = "SupabaseConfigError";
  }
}

let cached: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (cached) return cached;

  const url = import.meta.env.VITE_SUPABASE_URL;
  const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

  const missing: string[] = [];
  if (!url) missing.push("VITE_SUPABASE_URL");
  if (!publishableKey) missing.push("VITE_SUPABASE_PUBLISHABLE_KEY");
  if (missing.length > 0) throw new SupabaseConfigError(missing);

  cached = createClient(url, publishableKey, {
    auth: {
      // 게스트 신원은 기기에 남아야 나중에 계정으로 승계할 수 있다(D-062 3절).
      // 대화 상태(sessionStorage)와 달리 탭을 닫아도 유지된다.
      persistSession: true,
      autoRefreshToken: true,
      // 아직 OAuth 리다이렉트를 쓰지 않으므로 URL 파싱을 켜지 않는다.
      // 소셜 로그인을 붙일 때 true로 바꾼다.
      detectSessionInUrl: false,
    },
  });
  return cached;
}

/* 테스트가 환경변수를 바꿔 끼울 수 있게 캐시를 비운다. */
export function resetSupabaseClient(): void {
  cached = null;
}
