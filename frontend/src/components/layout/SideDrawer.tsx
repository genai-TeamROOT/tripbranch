/*
 * 역할: 모바일(<768px) 전용 푸시 드로어 — 왼쪽에 항상 존재하고, 본문(.tb-shell)이
 *   오른쪽으로 밀려나면서 드러난다. 일반적인 오버레이 드로어가 아니다.
 * 입력: 열림 여부, 링크 클릭 시 닫기 콜백.
 * 출력: 없음(라우팅은 SideDrawerContent가 한다).
 * 호출 시점: AppShell이 .tb-shell과 형제로 렌더한다.
 * 근거: package_D/DESIGN_SYSTEM.md §4 "푸시 드로어 동작".
 */

import { SideDrawerContent } from "./SideDrawerContent";

interface SideDrawerProps {
  open: boolean;
  onNavigate: () => void;
}

export function SideDrawer({ open, onNavigate }: SideDrawerProps) {
  return (
    <div
      className="fixed inset-y-0 left-0 z-10 flex w-[300px] flex-col bg-white md:hidden"
      aria-hidden={!open}
      inert={!open}
    >
      <div className="px-5 py-5">
        <span className="text-base font-bold text-ink">TripBranch</span>
      </div>
      <SideDrawerContent onNavigate={onNavigate} />
    </div>
  );
}
