/*
 * 역할: TripBranch 프론트엔드의 관문/홈/채팅 라우팅을 구성한다.
 * 입력: 브라우저 URL, AuthProvider가 확보한 신원.
 * 출력: LoginPage, 신원이 있어야 들어갈 수 있는 HomePage/ChatPage, 이전 URL 호환 리다이렉트.
 * 호출 시점: main.tsx가 앱을 렌더링할 때 최상위 컴포넌트로 호출된다.
 * TODO: 실제 세션 라우트가 생기면 /chat/:sessionId를 별도 보호 라우트로 추가한다.
 */

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireUser } from "./auth/RequireUser";
import { TripProvider } from "./state/TripContext";
import { HomePage } from "./pages/HomePage";
import { ChatPage } from "./pages/ChatPage";
import { LoginPage } from "./pages/LoginPage";
import { DeveloperChatPage } from "./pages/DeveloperChatPage";
import { DeveloperOpsPage } from "./pages/DeveloperOpsPage";

function App() {
  return (
    <AuthProvider>
      <TripProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/"
              element={
                <RequireUser>
                  <HomePage />
                </RequireUser>
              }
            />
            <Route
              path="/chat"
              element={
                <RequireUser>
                  <ChatPage />
                </RequireUser>
              }
            />
            <Route
              path="/dev-chat"
              element={
                <RequireUser>
                  <DeveloperChatPage />
                </RequireUser>
              }
            />
            {/* 운영 점검 화면은 사용자 신원과 무관한 내부 도구라 관문 밖에 둔다. */}
            <Route path="/dev-ops" element={<DeveloperOpsPage />} />
            <Route path="/confirm" element={<Navigate to="/chat" replace />} />
            <Route path="/results" element={<Navigate to="/chat" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </TripProvider>
    </AuthProvider>
  );
}

export default App;
