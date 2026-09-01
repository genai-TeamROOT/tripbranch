/*
 * 역할: 화면 상단의 프로스티드 헤더 — 모바일 전용 햄버거(드로어 열기) + 라벨이
 *   있을 때만 위치 pill + onBack이 있을 때만 뒤로가기.
 * 입력: 표시할 위치 라벨, 뒤로가기 콜백(있는 화면만).
 * 호출 시점: 신원이 필요한 화면들이 상단에 렌더링할 때.
 * 근거: DESIGN_SYSTEM.md §6.1(일반 모드) — 시트 모드는 바텀시트 내비게이션을
 *   붙일 때(§5) 추가한다.
 */

import { ChevronLeft, Menu } from "lucide-react";
import { cn } from "../../utils/cn";
import { useAppShell } from "./AppShellContext";

interface AppHeaderProps {
  locationLabel?: string | null;
  onBack?: () => void;
}

export function AppHeader({ locationLabel = null, onBack }: AppHeaderProps) {
  const { openDrawer } = useAppShell();

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
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white bg-white/60 text-ink shadow-resting backdrop-blur-md transition-colors hover:bg-white/80 md:hidden"
          >
            <Menu size={18} />
          </button>

          {onBack && (
            <button
              type="button"
              onClick={onBack}
              aria-label="뒤로가기"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white bg-white/60 text-ink shadow-resting backdrop-blur-md transition-colors hover:bg-white/80"
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
