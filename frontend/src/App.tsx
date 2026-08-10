/*
 * 역할: TripBranch 프론트엔드의 홈/채팅 라우팅을 구성한다.
 * 입력: 브라우저 URL.
 * 출력: HomePage, ChatPage, 이전 URL 호환 리다이렉트.
 * 호출 시점: main.tsx가 앱을 렌더링할 때 최상위 컴포넌트로 호출된다.
 * TODO: 실제 세션 라우트가 생기면 /chat/:sessionId를 별도 보호 라우트로 추가한다.
 */

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { TripProvider } from "./state/TripContext";
import { HomePage } from "./pages/HomePage";
import { ChatPage } from "./pages/ChatPage";
import { DeveloperChatPage } from "./pages/DeveloperChatPage";
import { DeveloperOpsPage } from "./pages/DeveloperOpsPage";

function App() {
  return (
    <TripProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/dev-chat" element={<DeveloperChatPage />} />
          <Route path="/dev-ops" element={<DeveloperOpsPage />} />
          <Route path="/confirm" element={<Navigate to="/chat" replace />} />
          <Route path="/results" element={<Navigate to="/chat" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </TripProvider>
  );
}

export default App;
