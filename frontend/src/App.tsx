/*
 * 역할: TripBranch 프론트엔드의 관문/홈/채팅 라우팅을 구성한다.
 * 입력: 브라우저 URL, AuthProvider가 확보한 신원.
 * 출력: LoginPage, 신원이 있어야 들어갈 수 있는 화면들(AppShell로 감싼 홈·채팅·
 *   취향 설정·위치 설정·일정), 이전 URL 호환 리다이렉트.
 * 호출 시점: main.tsx가 앱을 렌더링할 때 최상위 컴포넌트로 호출된다.
 * TODO: 실제 세션 라우트가 생기면 /chat/:sessionId를 별도 보호 라우트로 추가한다.
 *
 * 셸 안 라우팅. 취향·위치·일정 모두 사이드바에서 눌러도, 직접 주소로 들어와도
 * 같은 화면이 뜬다. 바텀시트 내비게이션(package_D/DESIGN_SYSTEM.md §5)을 붙일 때
 * 이 <Routes>를 baseLocation/sheetLocations 2단 렌더링으로 바꾼다.
 */

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireUser } from "./auth/RequireUser";
import { TripProvider } from "./state/TripContext";
import { AppShell } from "./components/layout/AppShell";
import { HomePage } from "./pages/HomePage";
import { ChatPage } from "./pages/ChatPage";
import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";
import { FindIdPage } from "./pages/FindIdPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { DeveloperChatPage } from "./pages/DeveloperChatPage";
import { DeveloperOpsPage } from "./pages/DeveloperOpsPage";

function AppShellRoutes() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/preferences" element={<PlaceholderPage title="취향 설정" />} />
        <Route path="/location" element={<PlaceholderPage title="위치 설정" />} />
        <Route path="/schedule" element={<PlaceholderPage title="일정" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}

function App() {
  return (
    <AuthProvider>
      <TripProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {/* 회원가입·아이디찾기·비밀번호찾기는 아직 백엔드가 없는 UI 목업이다(D-062 Phase 5). */}
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/find-id" element={<FindIdPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
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
            {/*
             * 신원이 필요한 화면 전부(/, /chat, /preferences, /location, /schedule,
             * 그리고 알 수 없는 경로)를 여기서 한 번에 받는다. AppShellRoutes 안의
             * 중첩 Routes가 실제 화면을 고른다 — RequireUser·AppShell을 화면마다
             * 반복하지 않기 위해서다.
             */}
            <Route
              path="*"
              element={
                <RequireUser>
                  <AppShellRoutes />
                </RequireUser>
              }
            />
          </Routes>
        </BrowserRouter>
      </TripProvider>
    </AuthProvider>
  );
}

export default App;
