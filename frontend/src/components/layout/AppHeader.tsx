/*
 * 역할: 화면 상단의 프로스티드 헤더 — 두 가지 모드로 스스로 판단해 모양을 바꾼다.
 *   일반 모드: 모바일 전용 햄버거(드로어 열기) + 라벨이 있을 때만 위치 pill.
 *   뒤로가기 화살표는 그리지 않는다(2026-09-07). 시트 모드: 우측 X 버튼만(지금은 죽은 분기).
 * 입력: 표시할 위치 라벨, 뒤로가기/닫기 콜백(있는 화면만).
 * 호출 시점: 신원이 필요한 화면들이 상단에 렌더링할 때.
 * 근거: DESIGN_SYSTEM.md §6.1, §5(isOpenAsSheet로 시트 여부 판정).
 */

import { ArrowRight, MapPinned, Menu, Navigation, X } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useIsDesktopSidebar } from "../../hooks/useIsDesktopSidebar";
import { isOpenAsSheet } from "../../state/sheetNav";
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
  /** 화살표로는 안 그린다(2026-09-07) — 시트 모드(죽은 분기)의 닫기 콜백과 헤더 접힘 판정에만 쓴다. */
  onBack?: () => void;
}

const FROSTED_BUTTON_CLASS =
  "flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white bg-white/60 text-ink shadow-resting backdrop-blur-md transition-colors hover:bg-white/80";

export function AppHeader({ location: locationChip = null, onBack }: AppHeaderProps) {
  const { drawerOpen, openDrawer, closeDrawer } = useAppShell();
  const location = useLocation();
  const navigate = useNavigate();
  const isDesktop = useIsDesktopSidebar();

  /*
   * **뒤로가기 화살표는 이제 어디서도 그리지 않는다**(2026-09-07). 데스크톱은
   * 전부터 안 그렸고(사이드바가 이미 돌아갈 길이라 화살표는 같은 일을 두 번
   * 함) — 모바일도 같은 이유로 뺐다. 모바일에서 돌아가는 길은 브라우저/제스처
   * 뒤로가기와 햄버거 드로어(새 채팅 등)다.
   *
   * onBack 자체는 그래도 받는다. 시트 모드(지금은 죽은 분기, 아래 참고)의 닫기
   * 버튼이 여전히 이 콜백을 쓰고, 아래 md:hidden 판정에도 쓴다.
   *
   * **띠 자체는 남긴다.** 접었더니 제목이 화면 맨 위에 붙어 위쪽 여백이
   * 사라졌었다(2026-09-06 사용자 확인) — 이 띠는 본문이 시작하기 전의 여백이다.
   */

  /*
   * **지금은 이 분기를 타는 화면이 없다**(2026-09-07). 위치·일정이 취향 설정과
   * 같은 전체 페이지로 바뀌면서, location.state.backgroundLocation을 실어
   * 보내는 곳이 앱에 더는 없다 — isOpenAsSheet는 항상 false를 돌려준다.
   *
   * 그래도 지우지 않는다. 시트 자체(BottomSheetLayer, AppShell의 스택 계산)는
   * 이 화면 전용이 아니라 범용 메커니즘이라, 나중에 다른 화면이 다시 시트로
   * 열리기로 하면 이 분기가 그대로 되살아난다. 바텀시트는 모바일 전용 패턴이라
   * 데스크톱에서는 시트로 열린 화면도 전체 페이지로 그려진다(AppShell 참고).
   */
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
        // 접는 판정은 **showBack이 아니라 onBack**으로 한다. 데스크톱에서 버튼은
        // 빠지지만 띠는 위쪽 여백으로 남아야 해서다 — showBack으로 재면 그 여백까지
        // 함께 접힌다. 위치 pill도 뒤로가기도 애초에 없는 화면(홈·채팅에서 위치를
        // 아직 못 정한 경우)만 접는다: 거기서는 데스크톱에 그릴 것이 정말 없다.
        // 모바일은 햄버거가 항상 있어야 하므로 어느 쪽이든 그대로 둔다.
        !locationChip && !onBack && "md:hidden",
      )}
    >
      <div className="relative flex items-center justify-between px-4 pb-3 pt-6">
        <div className="flex items-center gap-2">
          {/*
           * 여닫이다 — 열려 있을 때 다시 누르면 닫힌다(2026-09-07). 예전에는
           * openDrawer 만 불러서, 열어 둔 채로 누르면 아무 일도 안 났다.
           *
           * 셸이 이미 "밀려난 본문 아무 곳이나 누르면 닫기"를 갖고 있는데
           * (AppShell 의 onClickCapture), 그 캡처가 이 버튼보다 **먼저** 돌기
           * 때문에 둘이 서로를 무효화했다. data-drawer-toggle 표식을 보고 셸이
           * 이 버튼만 건너뛴다 — 여닫이는 이 버튼 하나가 온전히 갖는다.
           */}
          <button
            type="button"
            /* 셸의 탭-투-클로즈가 이 버튼은 건너뛰게 하는 표식이다(AppShell). */
            data-drawer-toggle=""
            onClick={() => (drawerOpen ? closeDrawer() : openDrawer())}
            aria-label={drawerOpen ? "메뉴 닫기" : "메뉴 열기"}
            aria-expanded={drawerOpen}
            className={cn(FROSTED_BUTTON_CLASS, "md:hidden")}
          >
            <Menu size={18} />
          </button>

          {locationChip && (
            <button
              type="button"
              onClick={() => navigate("/location")}
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
