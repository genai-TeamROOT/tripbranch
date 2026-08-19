/*
 * 역할: 신원이 없는 접근을 /login으로 돌려보내는 보호 라우트 래퍼.
 * 입력: AuthContext의 session/status, 현재 위치.
 * 출력: 자식 화면, 로딩 표시, 설정 오류 표시, 또는 /login 리다이렉트.
 * 호출 시점: App의 Routes에서 보호 대상 화면을 감쌀 때 호출된다.
 * TODO: 정식 로그인이 들어오면 "게스트 전용" 화면과 "계정 필요" 화면을 구분한다.
 */

import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function RequireUser({ children }: { children: ReactNode }) {
  const { session, status, error } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <main className="mx-auto flex min-h-screen max-w-xl items-center justify-center px-4">
        <p className="text-sm text-gray-600 dark:text-gray-400">불러오는 중이에요…</p>
      </main>
    );
  }

  /* 설정 누락은 로그인 화면으로 보내도 해결되지 않는다. 버튼을 눌러도 같은 지점에서
     실패하므로, 원인을 그대로 드러낸다. */
  if (status === "unconfigured") {
    return (
      <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-3 px-4">
        <h1 className="text-lg font-bold text-gray-900 dark:text-gray-100">
          인증 설정이 없어요
        </h1>
        <p className="text-sm text-gray-600 dark:text-gray-400">{error}</p>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          frontend/.env에 값을 채우고 개발 서버를 다시 시작해주세요.
        </p>
      </main>
    );
  }

  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
