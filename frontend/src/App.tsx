/*
 * 역할: TripBranch 프론트엔드의 관문/홈/채팅 라우팅을 구성한다.
 * 입력: 브라우저 URL, AuthProvider가 확보한 신원.
 * 출력: LoginPage, 신원이 있어야 들어갈 수 있는 화면들(AppShell로 감싼 홈·채팅·
 *   취향 설정·위치 설정·일정), 이전 URL 호환 리다이렉트.
 * 호출 시점: main.tsx가 앱을 렌더링할 때 최상위 컴포넌트로 호출된다.
 * TODO: 실제 세션 라우트가 생기면 /chat/:sessionId를 별도 보호 라우트로 추가한다.
 *
 * 셸 안 화면 표(홈·채팅·취향 설정·위치 설정·일정)는 AppShell이 감싸는
 * AppRoutes에 있다 — AppShell이 URL을 baseLocation(기반 화면)/sheetLocations
 * (위에 쌓인 바텀시트들)로 나눠 AppRoutes를 각각 다시 호출한다
 * (package_D/DESIGN_SYSTEM.md §5.3).
 */

import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireUser } from "./auth/RequireUser";
import { TripProvider } from "./state/TripContext";
import { AppShell } from "./components/layout/AppShell";

/*
 * 개발자 화면과 인증 화면은 따로 받아온다.
 *
 * - 개발자 화면(/dev-chat·/dev-ops)은 components/dev/ 17개를 끌고 오는데, 소스만
 *   227KB로 앱에서 가장 큰 덩어리다. 사용자는 이 경로에 오지 않으므로 첫 화면에
 *   실릴 이유가 없다.
 * - 인증 화면 4종은 로그인한 사용자가 다시 볼 일이 없다.
 *
 * AppShell(홈·채팅·취향·위치·일정)은 그대로 즉시 로딩한다 — 첫 화면이고,
 * 바텀시트로 뜨는 화면들이라 나중에 받아오면 시트가 빈 채로 올라온다.
 */
const LoginPage = lazy(() => import("./pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const SignupPage = lazy(() =>
  import("./pages/SignupPage").then((m) => ({ default: m.SignupPage })),
);
const FindIdPage = lazy(() =>
  import("./pages/FindIdPage").then((m) => ({ default: m.FindIdPage })),
);
const ResetPasswordPage = lazy(() =>
  import("./pages/ResetPasswordPage").then((m) => ({ default: m.ResetPasswordPage })),
);
const DeveloperChatPage = lazy(() =>
  import("./pages/DeveloperChatPage").then((m) => ({ default: m.DeveloperChatPage })),
);
const DeveloperOpsPage = lazy(() =>
  import("./pages/DeveloperOpsPage").then((m) => ({ default: m.DeveloperOpsPage })),
);

/* RequireUser의 로딩 표시와 같은 문구를 쓴다 — 화면 전환 중 문구가 바뀌지 않게. */
function RouteFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-sm text-gray-600 dark:text-gray-400">불러오는 중이에요…</p>
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <TripProvider>
        <BrowserRouter>
          <Suspense fallback={<RouteFallback />}>
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
               * 그리고 알 수 없는 경로)를 여기서 한 번에 받는다. AppShell 안의 AppRoutes가
               * 실제 화면을 고른다 — RequireUser를 화면마다 반복하지 않기 위해서다.
               */}
              <Route
                path="*"
                element={
                  <RequireUser>
                    <AppShell />
                  </RequireUser>
                }
              />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </TripProvider>
    </AuthProvider>
  );
}

export default App;
