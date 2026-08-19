/*
 * 역할: 서비스 진입 관문. 정식 로그인이 들어오기 전까지 게스트 신원만 발급한다.
 * 입력: 게스트 시작 버튼 클릭, 리다이렉트로 넘어온 원래 목적지.
 * 출력: 게스트 세션 발급 후 원래 목적지로 이동, 실패 시 오류 문구.
 * 호출 시점: 신원 없이 보호 라우트에 접근했거나 /login으로 직접 들어올 때 호출된다.
 * TODO: 카카오·이메일 로그인 버튼이 이 화면의 게스트 버튼 위에 추가된다(D-062 Phase 5).
 */

import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ErrorBanner } from "../components/ErrorBanner";

export function LoginPage() {
  const { session, status, error: authError, signInAsGuest } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  /* RequireUser가 넘겨준 원래 목적지. 직접 들어온 경우엔 홈으로 보낸다. */
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "ready" && session) {
    return <Navigate to={from} replace />;
  }

  async function handleGuestStart() {
    if (isLoading) return;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      await signInAsGuest();
      navigate(from, { replace: true });
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "게스트로 시작하지 못했어요.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-5 px-4 py-10">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">TripBranch</h1>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          지금 상황에 맞는 장소를 찾아드려요. 가입 없이 바로 시작할 수 있어요.
        </p>
      </div>

      {status === "unconfigured" ? (
        <section className="rounded-md border border-gray-200 p-3 text-sm text-gray-700 dark:border-gray-700 dark:text-gray-300">
          <p className="font-medium">인증 설정이 없어요</p>
          <p className="mt-1">{authError}</p>
          <p className="mt-1">frontend/.env를 채우고 개발 서버를 다시 시작해주세요.</p>
        </section>
      ) : null}

      {errorMessage ? <ErrorBanner message={errorMessage} /> : null}

      {/* 게스트로 시작해도 이용 기록이 남고, 나중에 계정을 연결하면 그 기록이 그대로
          이어진다(D-062 8절). 정식 로그인 도입 시 이 고지 자리를 수집 항목·목적·
          보관기간 안내로 확장한다(9-3절). */}
      <section className="rounded-md border border-gray-200 p-3 text-sm text-gray-700 dark:border-gray-700 dark:text-gray-300">
        게스트로 시작하면 대화 조건과 추천 이력이 이 기기에 연결돼요. 나중에 계정을
        만들면 지금까지의 기록을 그대로 이어서 쓸 수 있어요.
      </section>

      <button
        type="button"
        disabled={isLoading || status !== "ready"}
        onClick={() => void handleGuestStart()}
        className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
      >
        {isLoading ? "시작하는 중이에요…" : "게스트로 시작하기"}
      </button>
    </main>
  );
}
