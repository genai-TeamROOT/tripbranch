/* eslint-disable react-refresh/only-export-components */
/*
 * 역할: 세션을 확보·보관하고 API 클라이언트에 토큰 공급자를 등록한다.
 * 입력: Supabase auth 상태 변화, 게스트/이메일 인증 요청.
 * 출력: AuthProvider, useAuth hook.
 * 호출 시점: App이 최상위에서 감싸고, 인증 화면들과 RequireUser가 상태를 읽을 때 호출된다.
 *
 * **이메일 확인(Confirm email)이 켜져 있다.** 그래서 signUp()은 세션을 바로 주지
 * 않는다 — 사용자가 메일의 링크를 눌러야 계정이 열린다. 화면은 그 사실을 알리는
 * 중간 상태를 반드시 거쳐야 하고, 가입 직후 로그인된 것처럼 굴면 안 된다.
 *
 * TODO: 게스트→계정 승계(updateUser로 uid 유지, D-062 8절)는 2차 범위다. 지금은
 *   관문에서 처음부터 가입하는 경로만 있다.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Session } from "@supabase/supabase-js";
import { setAuthTokenProvider } from "../api/client";
import { getSupabaseClient, SupabaseConfigError } from "./supabaseClient";
import { authErrorMessage } from "./authErrors";

/* loading: 저장된 세션을 확인 중. ready: 확인 끝(session이 null일 수 있다).
   unconfigured: 환경변수가 없어 인증 자체를 시작할 수 없다. */
export type AuthStatus = "loading" | "ready" | "unconfigured";

export interface SignUpInput {
  name: string;
  email: string;
  password: string;
}

interface AuthContextValue {
  session: Session | null;
  status: AuthStatus;
  error: string | null;
  signInAsGuest: () => Promise<void>;
  /** 가입 요청을 보낸다. 확인 메일이 나가고, 세션은 아직 생기지 않는다. */
  signUpWithEmail: (input: SignUpInput) => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  sendPasswordReset: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let client;
    try {
      client = getSupabaseClient();
    } catch (configError) {
      /* 설정이 없으면 "그냥 비로그인으로 진행"하지 않는다. 그렇게 두면 프론트가
         토큰 없이 도는 상태가 화면에 드러나지 않은 채 계속 동작한다 — .env를 못 읽어
         전 Provider가 fake로 뜨던 것과 같은 실패다(D-042). */
      setStatus("unconfigured");
      setError(
        configError instanceof SupabaseConfigError
          ? configError.message
          : "인증 설정을 읽지 못했어요.",
      );
      return;
    }

    /* 토큰은 보관하지 않고 요청 시점에 클라이언트에서 직접 꺼낸다. 자동 갱신된
       토큰을 놓치지 않기 위해서다. */
    setAuthTokenProvider(async () => {
      const { data } = await client.auth.getSession();
      return data.session?.access_token ?? null;
    });

    let active = true;
    void client.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session ?? null);
      setStatus("ready");
    });

    const { data: listener } = client.auth.onAuthStateChange((_event, nextSession) => {
      if (!active) return;
      setSession(nextSession ?? null);
    });

    return () => {
      active = false;
      listener.subscription.unsubscribe();
      setAuthTokenProvider(null);
    };
  }, []);

  const signInAsGuest = useCallback(async () => {
    const client = getSupabaseClient();
    const { data, error: signInError } = await client.auth.signInAnonymously();
    if (signInError) {
      throw new Error(signInError.message || "게스트로 시작하지 못했어요.");
    }
    setSession(data.session ?? null);
  }, []);

  /*
   * 가입 요청. 이메일 확인이 켜져 있어 **여기서 세션이 생기지 않는다** — 돌려주는
   * 값도 없다. 호출부는 "메일을 보냈다"는 화면으로 넘어가야 한다.
   *
   * 이미 가입된 이메일이어도 오류를 내지 않는다. Supabase가 그 경우 사용자를 만든
   * 척하는 응답(identities가 빈 배열)을 돌려주는데, 이걸 풀어서 "이미 가입된
   * 이메일이에요"라고 알려주면 주소를 하나씩 넣어 가입 여부를 캐낼 수 있게 된다.
   * 그 보호를 우리가 벗기지 않는다 — 두 경우 모두 같은 안내를 보여준다.
   */
  const signUpWithEmail = useCallback(async ({ name, email, password }: SignUpInput) => {
    const client = getSupabaseClient();
    const { error: signUpError } = await client.auth.signUp({
      email,
      password,
      options: {
        /* identityLabel이 user_metadata.name을 읽는다 — 사이드바 표시가 바로 붙는다. */
        data: { name },
        emailRedirectTo: `${window.location.origin}/login`,
      },
    });
    if (signUpError) throw new Error(authErrorMessage(signUpError));
  }, []);

  const signInWithEmail = useCallback(async (email: string, password: string) => {
    const client = getSupabaseClient();
    const { data, error: signInError } = await client.auth.signInWithPassword({ email, password });
    if (signInError) throw new Error(authErrorMessage(signInError));
    setSession(data.session ?? null);
  }, []);

  /*
   * 재설정 메일을 보낸다. 링크는 새 비밀번호를 받는 화면으로 돌아온다.
   *
   * 가입되지 않은 주소여도 Supabase는 오류를 내지 않는다(계정 열거 방지). 화면도
   * 그 전제로 "보냈어요"라고만 말해야 한다 — 여기서 성공/실패를 갈라 보여주면
   * 그 자체가 가입 여부를 알려주는 신호가 된다.
   */
  const sendPasswordReset = useCallback(async (email: string) => {
    const client = getSupabaseClient();
    const { error: resetError } = await client.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password/new`,
    });
    if (resetError) throw new Error(authErrorMessage(resetError));
  }, []);

  /* 게스트에게 이 동작은 "나갔다 다시 들어오기"가 아니다 — 다시 로그인할 수단이
     없어 그 uid로 돌아갈 길이 사라진다. 호출부에서 확인을 받고 부른다. */
  const signOut = useCallback(async () => {
    const client = getSupabaseClient();
    const { error: signOutError } = await client.auth.signOut();
    if (signOutError) {
      throw new Error(signOutError.message || "세션을 해제하지 못했어요.");
    }
    setSession(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      status,
      error,
      signInAsGuest,
      signUpWithEmail,
      signInWithEmail,
      sendPasswordReset,
      signOut,
    }),
    [
      session,
      status,
      error,
      signInAsGuest,
      signUpWithEmail,
      signInWithEmail,
      sendPasswordReset,
      signOut,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth는 AuthProvider 안에서만 쓸 수 있어요.");
  return value;
}
