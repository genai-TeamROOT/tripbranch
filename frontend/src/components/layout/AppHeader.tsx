/*
 * 역할: 화면 상단의 프로스티드 헤더 — 두 가지 모드로 스스로 판단해 모양을 바꾼다.
 *   일반 모드: 모바일 전용 햄버거(드로어 열기) + 라벨이 있을 때만 위치 pill +
 *   onBack이 있을 때만 뒤로가기. 시트 모드: 우측 X 버튼만.
 * 입력: 표시할 위치 라벨, 뒤로가기/닫기 콜백(있는 화면만).
 * 호출 시점: 신원이 필요한 화면들이 상단에 렌더링할 때.
 * 근거: DESIGN_SYSTEM.md §6.1, §5(isOpenAsSheet로 시트 여부 판정).
 */

import { ChevronLeft, Menu, X } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useIsDesktopSidebar } from "../../hooks/useIsDesktopSidebar";
import { isOpenAsSheet } from "../../state/sheetNav";
import { cn } from "../../utils/cn";
import { useAppShell } from "./AppShellContext";

interface AppHeaderProps {
  locationLabel?: string | null;
  onBack?: () => void;
}

const FROSTED_BUTTON_CLASS =
  "flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white bg-white/60 text-ink shadow-resting backdrop-blur-md transition-colors hover:bg-white/80";

export function AppHeader({ locationLabel = null, onBack }: AppHeaderProps) {
  const { openDrawer } = useAppShell();
  const location = useLocation();
  const navigate = useNavigate();
  const isDesktop = useIsDesktopSidebar();

  // 바텀시트는 모바일 전용이라, 데스크톱에서는 시트로 열린 화면도 전체 페이지로
  // 그려진다(AppShell 참고) — 헤더도 시트 모드(X만)가 아니라 일반 모드로 보인다.
  if (isOpenAsSheet(location) && !isDesktop) {
    return (
      <div className="sticky top-0 z-20 flex justify-end px-4 pb-3 pt-5">
        <button
          type="button"
          onClick={onBack ?? (() => navigate(-1))}
          aria-label="닫기"
          className={FROSTED_BUTTON_CLASS}
        >
          <X size={20} />
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "sticky top-0 z-20 bg-gradient-to-b from-black/5 to-transparent",
        // 데스크톱은 햄버거가 md:hidden으로 빠지고, 위치 pill도 onBack도 없으면
        // 이 자리가 통째로 빈 그라디언트 띠로 남는다. 보여줄 게 없을 때는
        // 데스크톱에서 아예 접는다 — 모바일은 햄버거가 항상 있어야 하므로 그대로 둔다.
        !locationLabel && !onBack && "md:hidden",
      )}
    >
      <div className="relative flex items-center justify-between px-4 pb-3 pt-6">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={openDrawer}
            aria-label="메뉴 열기"
            className={cn(FROSTED_BUTTON_CLASS, "md:hidden")}
          >
            <Menu size={18} />
          </button>

          {onBack && (
            <button
              type="button"
              onClick={onBack}
              aria-label="뒤로가기"
              className={FROSTED_BUTTON_CLASS}
            >
              <ChevronLeft size={20} />
            </button>
          )}

          {locationLabel && (
            <span className="flex items-center gap-1.5 rounded-full border border-white bg-white/60 px-3 py-1.5 text-sm font-medium text-ink shadow-resting backdrop-blur-md">
              <span className="relative flex h-2.5 w-2.5" aria-hidden>
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
              </span>
              {locationLabel}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
