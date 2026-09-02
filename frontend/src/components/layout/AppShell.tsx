/*
 * 역할: 모든 화면을 감싸는 최상위 레이아웃 — 데스크톱 사이드바 + 모바일 푸시 드로어 +
 *   본문 셸(.tb-shell) + 그 위에 쌓이는 바텀시트 스택.
 * 입력: 없음(현재 URL을 useLocation으로 직접 읽는다).
 * 출력: 사이드바 접힘 상태(localStorage에 남긴다), 드로어 열림 상태, 기반 화면 +
 *   시트로 열린 화면들.
 * 호출 시점: App.tsx가 신원이 필요한 라우트(path="*")의 element로 이걸 직접 쓴다.
 * 근거: package_D/DESIGN_SYSTEM.md §4(레이아웃 셸), §5.3(App.tsx 조립 — 2단 렌더링).
 *
 * 바텀시트는 모바일 전용 패턴이다 — 태블릿·데스크톱(사이드바가 상시 보이는
 * 폭)에서는 위치·일정도 시트로 겹쳐 뜨우지 않고 그냥 지금 화면을 그대로
 * 전체 페이지로 그린다. location.state.backgroundLocation은 계속 실려
 * 있지만(모바일로 다시 좁아지면 바로 시트로 되돌아가야 하니 지우지 않는다),
 * 데스크톱에서는 무시한다.
 */

import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useIsDesktopSidebar } from "../../hooks/useIsDesktopSidebar";
import { buildLocationStack } from "../../state/sheetNav";
import { AppRoutes } from "./AppRoutes";
import { AppShellProvider, useAppShell } from "./AppShellContext";
import { BottomSheetLayer } from "./BottomSheetLayer";
import { DesktopSidebar } from "./DesktopSidebar";
import { SideDrawer } from "./SideDrawer";

const COLLAPSED_KEY = "tb_sidebar_collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function AppShellInner() {
  const { drawerOpen, closeDrawer } = useAppShell();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const location = useLocation();
  const navigate = useNavigate();
  const isDesktop = useIsDesktopSidebar();

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      /* 저장 실패해도 화면 동작에는 영향 없다. */
    }
  }, [collapsed]);

  const stack = buildLocationStack(location);
  // 데스크톱은 지금 위치를 그대로 기반 화면으로 그린다 — 쌓인 시트가 있어도
  // 겹쳐 띄우지 않는다(모바일 전용 패턴).
  const baseLocation = isDesktop ? location : stack[0];
  const sheetLocations = isDesktop ? [] : stack.slice(1);

  return (
    <div className="tb-app-root">
      <DesktopSidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <SideDrawer open={drawerOpen} onNavigate={closeDrawer} />
      <div
        className={`tb-shell ${drawerOpen ? "tb-shell--pushed" : ""}`}
        // 드로어가 열려 본문이 오른쪽으로 밀려난 상태에서, 밀려난 본문 아무 곳이나
        // 누르면 바깥을 누른 것으로 보고 드로어를 닫는다(탭-투-클로즈).
        onClickCapture={drawerOpen ? closeDrawer : undefined}
      >
        <AppRoutes location={baseLocation} />
        {sheetLocations.map((sheetLocation, depth) => (
          <BottomSheetLayer key={sheetLocation.key} depth={depth} onDismiss={() => navigate(-1)}>
            <AppRoutes location={sheetLocation} />
          </BottomSheetLayer>
        ))}
      </div>
    </div>
  );
}

export function AppShell() {
  return (
    <AppShellProvider>
      <AppShellInner />
    </AppShellProvider>
  );
}
