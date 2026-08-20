/*
 * 역할: 브라우저 위치를 다시 확인할 시점을 한 곳에서 판정한다.
 * 입력: 현재 위치값, 마지막 브라우저 위치 확인 시각(ms), 기준 시각(ms).
 * 출력: 위치 재확인 질문 필요 여부와 화면 표시용 경과 분.
 */

/** 사용자가 새 위치를 선택한 뒤 다시 확인을 묻기까지의 시간. */
export const LOCATION_RECONFIRM_AFTER_MS = 30 * 60 * 1000;

export function isLocationRefreshDue(
  deviceLocation: string | null,
  capturedAt: number | null,
  now: number = Date.now(),
): boolean {
  if (deviceLocation === null) return false;
  return capturedAt === null || now - capturedAt >= LOCATION_RECONFIRM_AFTER_MS;
}

export function getLocationAgeMinutes(
  capturedAt: number | null,
  now: number = Date.now(),
): number | null {
  if (capturedAt === null) return null;
  return Math.max(1, Math.floor((now - capturedAt) / 60_000));
}
