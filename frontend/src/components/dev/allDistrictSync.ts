/*
 * 역할: 전 구 갱신 순회가 쓰는 예산 계산과 구별 실행/건너뛰기 판정.
 * 입력: 구별 대조 결과, 오늘 detailIntro2 사용량, 지금까지 쓴 호출 수.
 * 출력: 예상 상세조회 수, 남은 한도, 이 구를 지금 돌릴 수 있는지와 못 돌릴 이유.
 * 호출 시점: DeveloperOpsPage의 순회 루프와 AllDistrictSyncPanel이 부른다.
 *
 * 화면에서 떼어 둔다. 여기가 "무엇을 건너뛰었나"를 정하는 유일한 자리라서,
 * 순회 로직과 표 문구가 같은 함수를 봐야 동작과 설명이 갈라지지 않는다.
 */

import type { DbStatus, ReconcileResult, SyncDistrict, SyncJob } from "../../api/dev";

/** 구 하나가 전 구 순회에서 어디까지 갔는지. */
export type AllSyncOutcome =
  "pending" | "reconciled" | "running" | "success" | "skipped" | "failed";

export type AllSyncEntry = {
  areaCode: string;
  districtCode: string;
  districtName: string | null;
  /** 1단계 결과. null이면 아직 대조하지 않았거나 대조가 실패했다. */
  reconcile: ReconcileResult | null;
  reconcileError: string | null;
  outcome: AllSyncOutcome;
  /** 건너뛴 이유. 한도 때문인지 대조 실패 때문인지 구분해야 다음 조치가 갈린다. */
  skipReason: string | null;
  job: SyncJob | null;
  applyError: string | null;
};

export type AllSyncPhase = "idle" | "reconciling" | "reviewing" | "applying" | "done";

export type AllSyncState = {
  phase: AllSyncPhase;
  entries: AllSyncEntry[];
  /** 지금 다루고 있는 entries 인덱스. 진행 표시에만 쓴다. */
  cursor: number;
  /** 이번 순회가 실제로 쓴 detailIntro2 횟수. 예상치가 아니라 job 결과의 실측이다. */
  spentDetailCalls: number;
  /** 한도 소진 응답을 실제로 받았는지. 받았으면 남은 구는 전부 건너뛴다. */
  quotaExhausted: boolean;
  error: string | null;
};

export const EMPTY_ALL_SYNC_STATE: AllSyncState = {
  phase: "idle",
  entries: [],
  cursor: 0,
  spentDetailCalls: 0,
  quotaExhausted: false,
  error: null,
};

/** 서버가 한도 소진으로 상세조회를 멈췄음을 알리는 코드. place_sync.py와 같은 문자열. */
export const QUOTA_EXCEEDED_CODE = "TOUR_DETAIL_QUOTA_EXCEEDED";

export function createEntry(district: SyncDistrict): AllSyncEntry {
  return {
    areaCode: district.area_code,
    districtCode: district.district_code,
    districtName: district.district_name,
    reconcile: null,
    reconcileError: null,
    outcome: "pending",
    skipReason: null,
    job: null,
    applyError: null,
  };
}

/** 이 구를 반영하면 나갈 detailIntro2 횟수.
 *
 * 변경분만이 아니라 지난 실행에서 못 채운 건(pending·failed)도 함께 나간다 —
 * 서버의 `_select_targets`가 그렇게 동작한다. 빼고 세면 화면이 "15회"라고
 * 해놓고 실제로는 157회를 쓴다.
 *
 * 상세조회 제외분(detail_excluded_ids)은 넣지 않는다. 구 단위 패널의 기본값과
 * 같다 — 수정시각이 그대로인 장소라 상세 내용은 안 바뀌었다고 본다. */
export function plannedDetailCalls(reconcile: ReconcileResult): number {
  return reconcile.detail_content_ids.length + reconcile.detail_backfill_ids.length;
}

/** 오늘 남은 detailIntro2 한도. 한도 설정이 없으면 null(제한 없음으로 다룬다).
 *
 * 이 값은 **어림이고 낙관적이다.** 빼는 쪽 사용량(`detail_calls_today.count`)이
 * 하한이기 때문이다 — 재시도는 세지 않고, 완료 처리를 못 한 실행은 사용량이
 * 비어 있다. 그래서 예산을 다 쓰지 않았는데도 서버가 한도 소진을 돌려줄 수 있고,
 * 그때는 `quotaExhausted`로 갈아탄다. */
export function remainingDetailBudget(
  detailCallsToday: DbStatus["detail_calls_today"] | null,
): number | null {
  if (!detailCallsToday || detailCallsToday.daily_limit === null) return null;
  return Math.max(0, detailCallsToday.daily_limit - detailCallsToday.count);
}

/** 이 구를 지금 반영할 수 있는지. 못 하면 건너뛸 이유를 함께 준다.
 *
 * 판정을 순회 로직에서 떼어 둔다 — 여기가 "무엇을 건너뛰었나"를 정하는 유일한
 * 자리라서, 화면 문구와 실제 동작이 갈라지지 않으려면 한 곳에 있어야 한다. */
export function planDistrict(input: {
  entry: AllSyncEntry;
  spent: number;
  budget: number | null;
  quotaExhausted: boolean;
}): { run: true } | { run: false; reason: string } {
  const { entry, spent, budget, quotaExhausted } = input;
  if (entry.reconcile === null) {
    return { run: false, reason: "대조에 실패해 반영할 스냅샷이 없어요." };
  }
  if (quotaExhausted) {
    return {
      run: false,
      reason: "앞 구에서 오늘 상세조회 한도가 소진됐어요. 내일 다시 실행하세요.",
    };
  }
  const planned = plannedDetailCalls(entry.reconcile);
  if (budget !== null && spent + planned > budget) {
    return {
      run: false,
      reason: `상세조회 ${planned}회가 필요한데 남은 한도가 ${Math.max(0, budget - spent)}회예요.`,
    };
  }
  return { run: true };
}

/** job 결과가 "오늘 한도를 다 썼다"를 담고 있는지. */
export function jobHitQuota(job: SyncJob | null): boolean {
  return Boolean(job?.result?.error_summary?.[QUOTA_EXCEEDED_CODE]);
}
