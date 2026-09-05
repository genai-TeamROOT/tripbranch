/*
 * 역할: 화면 상단의 프로스티드 헤더 — 두 가지 모드로 스스로 판단해 모양을 바꾼다.
 *   일반 모드: 모바일 전용 햄버거(드로어 열기) + 라벨이 있을 때만 위치 pill +
 *   onBack이 있을 때만 뒤로가기. 시트 모드: 우측 X 버튼만.
 * 입력: 표시할 위치 라벨, 뒤로가기/닫기 콜백(있는 화면만).
 * 호출 시점: 신원이 필요한 화면들이 상단에 렌더링할 때.
 * 근거: DESIGN_SYSTEM.md §6.1, §5(isOpenAsSheet로 시트 여부 판정).
 */

import { ArrowRight, ChevronLeft, MapPinned, Menu, Navigation, X } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useIsDesktopSidebar } from "../../hooks/useIsDesktopSidebar";
import { isOpenAsSheet, sheetState } from "../../state/sheetNav";
import { cn } from "../../utils/cn";
import type { LocationChipModel } from "../../utils/locationChip";
import { useAppShell } from "./AppShellContext";

interface AppHeaderProps {
  /*
   * 위치 칩에 그릴 모양(utils/locationChip). 문자열 하나가 아니라 모델을 받는
   * 이유는, 출발지와 검색 기준이 다를 때 둘 다 보여야 하기 때문이다 — 하나만
   * 고르면 카드의 이동시간을 어디서 쟀는지가 화면에서 사라진다(D-067).
   */
  location?: LocationChipModel | null;
  onBack?: () => void;
}

const FROSTED_BUTTON_CLASS =
  "flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white bg-white/60 text-ink shadow-resting backdrop-blur-md transition-colors hover:bg-white/80";

export function AppHeader({ location: locationChip = null, onBack }: AppHeaderProps) {
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
        !locationChip && !onBack && "md:hidden",
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

          {locationChip && (
            <button
              type="button"
              onClick={() => navigate("/location", { state: sheetState(location) })}
              aria-label={`위치 설정으로 이동 (${locationChip.description})`}
              /* min-w-0을 두어야 안쪽 이름이 줄어들 수 있다. 없으면 칩이 제 내용
                 폭을 고집해 좁은 화면에서 헤더 밖으로 밀려난다. */
              className="flex min-w-0 items-center gap-1.5 rounded-full border border-white bg-white/60 px-3 py-1.5 text-sm font-medium text-ink shadow-resting backdrop-blur-md transition-colors hover:bg-white/80"
            >
              {locationChip.kind === "pair" && (
                <>
                  <LocationChipIcon isDeviceLocation={locationChip.isDeviceLocation} role="origin" />
                  <span className="truncate">{locationChip.origin}</span>
                  <ArrowRight size={13} className="shrink-0 text-muted" aria-hidden />
                </>
              )}
              <LocationChipIcon
                isDeviceLocation={locationChip.kind === "single" && locationChip.isDeviceLocation}
                role={locationChip.kind === "single" ? "single" : "center"}
              />
              <span className="truncate">
                {locationChip.kind === "single" ? locationChip.name : locationChip.center}
              </span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/*
 * 칩 안의 아이콘. 위치 설정 화면과 같은 것을 쓴다 — 출발지는 Navigation, 검색
 * 기준은 MapPinned(바닥 원이 깔린 핀, "그 지점"이 아니라 "그 자리 주변"이라는 뜻).
 * 두 화면이 같은 모양을 써야 한쪽에서 배운 뜻이 다른 쪽에서도 통한다.
 *
 * **깜빡이는 초록 점은 기기 좌표일 때만 쓴다.** 전에는 이 점이 무조건 붙어 있었는데,
 * 그 자리에 뜨는 값은 검색 기준이라 사용자가 광화문역에 있지도 않은데 "실시간 내
 * 위치"가 광화문역 옆에서 깜빡였다. 이제 이 점의 뜻은 하나다 — 지금 GPS를 쓰는 중.
 */
function LocationChipIcon({
  isDeviceLocation,
  role,
}: {
  isDeviceLocation: boolean;
  role: "origin" | "center" | "single";
}) {
  if (isDeviceLocation) {
    return (
      <span className="relative flex h-2.5 w-2.5 shrink-0" aria-hidden>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
      </span>
    );
  }
  const Icon = role === "origin" ? Navigation : MapPinned;
  return <Icon size={13} className="shrink-0 text-brand" aria-hidden />;
}
