/*
 * 역할: 인증용 Supabase 클라이언트를 지연 생성하고, "재설정 링크로 들어왔다"는
 *   사실을 기억한다.
 * 입력: VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY 환경변수.
 * 출력: SupabaseClient 싱글턴 또는 SupabaseConfigError, 그리고 비밀번호 재설정 신호.
 * 호출 시점: AuthProvider가 세션을 확인하거나 게스트·이메일 인증을 요청할 때.
 * TODO: 소셜 provider 연동(D-062 Phase 5)도 이 클라이언트를 쓴다.
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

/*
 * 재설정 링크로 들어온 세션인지를 기억한다.
 *
 * **왜 모듈에 두는가.** PASSWORD_RECOVERY는 클라이언트가 처음 초기화되면서 URL
 * 조각을 읽을 때 딱 한 번 나온다. 컴포넌트 안에서만 구독하면 놓칠 수 있다 —
 * StrictMode는 effect를 두 번 돌리는데 두 번째에는 클라이언트가 이미 캐시돼 있어
 * 초기화가 다시 일어나지 않는다. 그래서 클라이언트를 만드는 그 자리에서(초기화가
 * 끝나기 전에) 붙잡아 모듈에 남긴다.
 *
 * **주소창을 우리가 읽지 않는 것이 요점이다.** #type=recovery는 아무나 손으로 붙일
 * 수 있다. 그걸 근거로 삼으면 로그인된 기기에서 주소만 고쳐 비밀번호를 바꿀 수
 * 있다. 이 이벤트는 Supabase가 링크의 토큰을 서버에 확인시킨 뒤에만 나온다.
 */
let passwordRecovery = false;
const recoveryListeners = new Set<(active: boolean) => void>();

function setPasswordRecovery(next: boolean): void {
  if (passwordRecovery === next) return;
  passwordRecovery = next;
  for (const listener of recoveryListeners) listener(next);
}

/** 지금 화면이 재설정 링크가 세운 세션 위에 있는지. */
export function isPasswordRecoveryActive(): boolean {
  return passwordRecovery;
}

/** 비밀번호를 실제로 바꾼 뒤에 끈다 — 링크 한 번에 변경 한 번이다. */
export function clearPasswordRecovery(): void {
  setPasswordRecovery(false);
}

export function onPasswordRecoveryChange(listener: (active: boolean) => void): () => void {
  recoveryListeners.add(listener);
  return () => {
    recoveryListeners.delete(listener);
  };
}

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
      // 메일 링크(#access_token=…&type=recovery|signup)를 읽어 세션을 세운다.
      // 끄면 비밀번호 재설정 링크가 아무 일도 하지 않는다 — 세션이 서지 않아
      // /reset-password/new가 항상 "만료된 링크"로 보인다.
      detectSessionInUrl: true,
    },
  });

  /* createClient 바로 뒤, 같은 tick에 붙인다. 초기화는 비동기라 이 시점에는 아직
     끝나지 않았고, 따라서 PASSWORD_RECOVERY를 놓치지 않는다. */
  cached.auth.onAuthStateChange((event) => {
    if (event === "PASSWORD_RECOVERY") setPasswordRecovery(true);
    else if (event === "SIGNED_OUT") setPasswordRecovery(false);
  });

  return cached;
}

/* 테스트가 환경변수를 바꿔 끼울 수 있게 캐시를 비운다. 재설정 신호도 같이 끈다 —
   테스트 하나가 켠 값이 다음 테스트로 새면 안 된다. */
export function resetSupabaseClient(): void {
  cached = null;
  passwordRecovery = false;
}
