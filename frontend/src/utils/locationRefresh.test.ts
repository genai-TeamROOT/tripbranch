import { describe, expect, test } from "vitest";
import {
  LOCATION_RECONFIRM_AFTER_MS,
  getLocationAgeMinutes,
  isLocationRefreshDue,
} from "./locationRefresh";

const JONGNO_LOCATION = "37.5796,126.9769";
const NOW = 1_786_000_000_000;

describe("location refresh timing", () => {
  test("위치가 없으면 재확인 질문을 띄우지 않는다", () => {
    expect(isLocationRefreshDue(null, null, NOW)).toBe(false);
  });

  test("마지막 확인 후 30분 전까지는 기존 위치를 계속 사용한다", () => {
    const capturedAt = NOW - LOCATION_RECONFIRM_AFTER_MS + 1;

    expect(isLocationRefreshDue(JONGNO_LOCATION, capturedAt, NOW)).toBe(false);
  });

  test("마지막 확인 후 정확히 30분이 지나면 재확인을 묻는다", () => {
    const capturedAt = NOW - LOCATION_RECONFIRM_AFTER_MS;

    expect(isLocationRefreshDue(JONGNO_LOCATION, capturedAt, NOW)).toBe(true);
    expect(getLocationAgeMinutes(capturedAt, NOW)).toBe(30);
  });

  test("현재 위치를 다시 가져오면 그 시각부터 새 30분을 계산한다", () => {
    const refreshedAt = NOW;

    expect(isLocationRefreshDue(JONGNO_LOCATION, refreshedAt, NOW + LOCATION_RECONFIRM_AFTER_MS - 1)).toBe(
      false,
    );
    expect(isLocationRefreshDue(JONGNO_LOCATION, refreshedAt, NOW + LOCATION_RECONFIRM_AFTER_MS)).toBe(
      true,
    );
  });
});
