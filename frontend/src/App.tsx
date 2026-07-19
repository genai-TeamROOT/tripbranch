/*
 * 역할: TripBranch 프론트엔드의 라우팅과 페이지 접근 가드를 구성한다.
 * 입력: 브라우저 URL, TripContext에 저장된 해석 조건과 추천 결과 상태.
 * 출력: 현재 경로에 맞는 페이지 컴포넌트 또는 안전한 리다이렉트.
 * 호출 시점: main.tsx가 앱을 렌더링할 때 최상위 컴포넌트로 호출된다.
 * TODO: 라우트가 늘어나면 보호 라우트와 레이아웃을 별도 모듈로 분리한다.
 */

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { TripProvider, useTripState } from "./state/TripContext";
import { InputPage } from "./pages/InputPage";
import { ConfirmPage } from "./pages/ConfirmPage";
import { ResultsPage } from "./pages/ResultsPage";

function RequireConditions({ children }: { children: ReactNode }) {
  const { interpreted_conditions } = useTripState();
  return interpreted_conditions ? children : <Navigate to="/" replace />;
}

function RequireResults({ children }: { children: ReactNode }) {
  const { interpreted_conditions, recommendations, unverified_recommendations } = useTripState();
  const hasResults = recommendations.length > 0 || unverified_recommendations.length > 0;
  return interpreted_conditions && hasResults ? children : <Navigate to="/" replace />;
}

function App() {
  return (
    <TripProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<InputPage />} />
          <Route
            path="/confirm"
            element={
              <RequireConditions>
                <ConfirmPage />
              </RequireConditions>
            }
          />
          <Route
            path="/results"
            element={
              <RequireResults>
                <ResultsPage />
              </RequireResults>
            }
          />
        </Routes>
      </BrowserRouter>
    </TripProvider>
  );
}

export default App;
