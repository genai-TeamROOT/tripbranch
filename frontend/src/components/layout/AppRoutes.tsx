/*
 * 역할: 신원이 필요한 화면(홈·채팅·취향 설정·위치 설정·일정)의 라우트 표를 정의한다.
 * 입력: 매칭에 쓸 location — 실제 브라우저 위치일 수도, 시트로 열린 배경/전경
 *   위치일 수도 있다(AppShell이 baseLocation/sheetLocations로 나눠 넘긴다).
 * 출력: 해당 location에 맞는 페이지.
 * 호출 시점: AppShell이 기반 화면 한 번, 쌓인 시트마다 한 번씩 호출한다.
 * 근거: package_D/DESIGN_SYSTEM.md §5.3 — 같은 라우트 표를 location만 바꿔 재사용해
 *   바텀시트 스택을 만든다.
 */

import { Navigate, Route, Routes, type Location } from "react-router-dom";
import { ChatPage } from "../../pages/ChatPage";
import { HomePage } from "../../pages/HomePage";
import { PlaceholderPage } from "../../pages/PlaceholderPage";

export function AppRoutes({ location }: { location: Location }) {
  return (
    <Routes location={location}>
      <Route path="/" element={<HomePage />} />
      <Route path="/chat" element={<ChatPage />} />
      <Route path="/preferences" element={<PlaceholderPage title="취향 설정" />} />
      <Route path="/location" element={<PlaceholderPage title="위치 설정" />} />
      <Route path="/schedule" element={<PlaceholderPage title="일정" />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
