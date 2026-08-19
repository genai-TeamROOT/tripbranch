/* eslint-disable react-refresh/only-export-components */
/*
 * 역할: 게스트 세션을 확보·보관하고 API 클라이언트에 토큰 공급자를 등록한다.
 * 입력: Supabase auth 상태 변화, 게스트 로그인 요청.
 * 출력: AuthProvider, useAuth hook.
 * 호출 시점: App이 최상위에서 감싸고, LoginPage/RequireUser가 상태를 읽을 때 호출된다.
 * TODO: 정식 로그인(D-062 Phase 5)이 들어오면 linkIdentity 경로를 여기에 추가한다.
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

/* loading: 저장된 세션을 확인 중. ready: 확인 끝(session이 null일 수 있다).
   unconfigured: 환경변수가 없어 인증 자체를 시작할 수 없다. */
export type AuthStatus = "loading" | "ready" | "unconfigured";

interface AuthContextValue {
  session: Session | null;
  status: AuthStatus;
  error: string | null;
  signInAsGuest: () => Promise<void>;
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
    () => ({ session, status, error, signInAsGuest, signOut }),
    [session, status, error, signInAsGuest, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth는 AuthProvider 안에서만 쓸 수 있어요.");
  return value;
}
