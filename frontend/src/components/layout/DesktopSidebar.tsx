/*
 * 역할: 768px 이상에서 본문 왼쪽에 상시 붙는 사이드바. 펼침 272px / 접힘 72px 레일.
 * 입력: 접힘 여부(부모가 보관), 현재 라우트.
 * 출력: 펼침/접힘 토글, 접힘 상태에서의 라우트 이동.
 * 호출 시점: AppShell이 셸 왼쪽에 렌더한다. 모바일에서는 CSS(.tb-sidebar)로 숨는다.
 * 근거: DESIGN_SYSTEM.md 4장(셸) · 6.17(사이드바).
 */

import { useLocation, useNavigate } from "react-router-dom";
import { Home, MapPin, PanelLeftClose, PanelLeftOpen, Route, Sparkles } from "lucide-react";
import { sheetState } from "../../state/sheetNav";
import { useTripDispatch, useTripState } from "../../state/TripContext";
import { SideDrawerContent } from "./SideDrawerContent";

interface DesktopSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const RAIL_ICON_CLASS = "flex h-10 w-10 items-center justify-center rounded-full transition-colors";

export function DesktopSidebar({ collapsed, onToggle }: DesktopSidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const dispatch = useTripDispatch();
  const state = useTripState();

  const hasConversation = state.messages.length > 0;

  /*
   * "홈"만 판정과 동작이 다르다 — 대화가 남아 있으면 비활성으로 그리고,
   * 누르면 세션을 지운다(6.17). 나머지는 단순 이동이다.
   */
  const railItems: Array<{
    key: string;
    label: string;
    icon: typeof Home;
    active: boolean;
    onClick: () => void;
  }> = [
    {
      key: "home",
      label: "홈",
      icon: Home,
      active: location.pathname === "/" && !hasConversation,
      onClick: () => {
        dispatch({ type: "RESET" });
        navigate("/");
      },
    },
    {
      key: "preferences",
      label: "취향 설정",
      icon: Sparkles,
      active: location.pathname === "/preferences",
      onClick: () => navigate("/preferences"),
    },
    {
      key: "location",
      label: "위치 설정",
      icon: MapPin,
      active: location.pathname === "/location",
      // 위치·일정은 새 페이지가 아니라 지금 화면 위에 바텀시트로 뜬다(§5).
      onClick: () => navigate("/location", { state: sheetState(location) }),
    },
    {
      key: "schedule",
      label: "일정",
      icon: Route,
      active: location.pathname === "/schedule",
      onClick: () => navigate("/schedule", { state: sheetState(location) }),
    },
  ];

  return (
    <aside className={`tb-sidebar ${collapsed ? "tb-sidebar--collapsed" : ""}`}>
      {collapsed ? (
        <div className="flex flex-col items-center gap-2 py-5">
          <button
            type="button"
            onClick={onToggle}
            aria-label="사이드바 펼치기"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-chip hover:text-ink"
          >
            <PanelLeftOpen size={18} />
          </button>
          <div className="my-1 h-px w-8 bg-border" />
          {railItems.map((item) => (
            <button
              key={item.key}
              type="button"
              title={item.label}
              aria-label={item.label}
              onClick={item.onClick}
              className={`${RAIL_ICON_CLASS} ${
                item.active ? "bg-brand text-white" : "text-brand hover:bg-chip"
              }`}
            >
              <item.icon size={18} />
            </button>
          ))}
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between px-5 py-5">
            <span className="text-base font-bold text-ink">TripBranch</span>
            <button
              type="button"
              onClick={onToggle}
              aria-label="사이드바 접기"
              aria-expanded={true}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-chip hover:text-ink"
            >
              <PanelLeftClose size={18} />
            </button>
          </div>
          <SideDrawerContent />
        </>
      )}
    </aside>
  );
}
