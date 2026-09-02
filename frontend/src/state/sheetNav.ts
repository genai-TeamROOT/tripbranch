/*
 * 역할: 화면을 새 페이지로 갈아치우지 않고 아래에서 올라오는 시트로 여닫는 데
 *   필요한 위치(Location) 계산을 모은다. React Router의 "background location"
 *   패턴을 일반화했다.
 * 근거: package_D/DESIGN_SYSTEM.md §5.1(`lib/sheetNav.ts`) — 이 저장소 관례상
 *   navigate 관련 순수 로직은 state/ 아래 둔다.
 */

import type { Location } from "react-router-dom";

const SHEET_PATH_PATTERNS = [/^\/location$/, /^\/schedule$/, /^\/place\//];

export function isSheetPath(pathname: string): boolean {
  return SHEET_PATH_PATTERNS.some((pattern) => pattern.test(pathname));
}

interface LocationState {
  backgroundLocation?: Location;
  [key: string]: unknown;
}

/** 시트로 열 때 navigate()/<Link>에 넘길 state를 만든다. */
export function sheetState(background: Location, extra?: Record<string, unknown>): LocationState {
  return { ...extra, backgroundLocation: background };
}

/** 지금 이 화면이 시트로 렌더링 중인가(= 전체 페이지가 아닌가). */
export function isOpenAsSheet(location: Location): boolean {
  return Boolean((location.state as LocationState | null)?.backgroundLocation);
}

/**
 * location.state.backgroundLocation을 뿌리까지 거슬러 올라가
 * [기반 페이지, ...그 위에 쌓인 시트들] 순서로 반환한다.
 * 시트 위에서 또 시트를 열면 이전 location이 그대로 실려 가므로
 * 깊이에 상관없이 스택이 복원된다.
 */
export function buildLocationStack(location: Location): Location[] {
  const stack: Location[] = [];
  const seen = new Set<string>();
  let current: Location | undefined = location;
  while (current && !seen.has(current.key)) {
    seen.add(current.key);
    stack.unshift(current);
    current = (current.state as LocationState | null)?.backgroundLocation;
  }
  return stack;
}
