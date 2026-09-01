/*
 * 역할: 모든 화면을 감싸는 최상위 레이아웃 — 데스크톱 사이드바 + 모바일 푸시 드로어 +
 *   본문 셸(.tb-shell).
 * 입력: children(라우트가 고른 페이지).
 * 출력: 사이드바 접힘 상태(localStorage에 남긴다), 드로어 열림 상태.
 * 호출 시점: App.tsx가 신원이 필요한 라우트들을 이걸로 감싼다.
 * 근거: package_D/DESIGN_SYSTEM.md §4(레이아웃 셸).
 */

import { useEffect, useState } from "react";
import { AppShellProvider, useAppShell } from "./AppShellContext";
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

function AppShellInner({ children }: { children: React.ReactNode }) {
  const { drawerOpen, closeDrawer } = useAppShell();
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      /* 저장 실패해도 화면 동작에는 영향 없다. */
    }
  }, [collapsed]);

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
        {children}
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AppShellProvider>
      <AppShellInner>{children}</AppShellInner>
    </AppShellProvider>
  );
}
