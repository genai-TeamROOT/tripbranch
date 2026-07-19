// 라우트 가드 컴포넌트. interpreted_conditions가 없으면 "/"로 리다이렉트한다.
// 사용법: /confirm, /results처럼 이전 단계 상태가 반드시 필요한 라우트를 이 컴포넌트로 감싼다
// (App.tsx 참고). 새 보호 라우트가 필요하면 조건을 이 컴포넌트에 추가하거나 유사한
// 가드 컴포넌트를 하나 더 만들 것(예: 결과가 반드시 있어야 하는 페이지가 생기면).

import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useTripState } from "../context/useTripState";

// Guards /confirm and /results: without interpreted_conditions there is
// nothing to confirm or recommend against, so send the user back to start.
export function RequireConditions({ children }: { children: ReactNode }) {
  const { interpreted_conditions } = useTripState();

  if (!interpreted_conditions) {
    return <Navigate to="/" replace />;
  }

  return children;
}
