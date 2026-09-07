import type { ScheduleItem, TravelMode } from "../types";

const MODE_LABEL: Record<TravelMode, string> = {
  walking: "도보 이동",
  transit: "대중교통 이동",
  driving: "자동차 이동",
};

/**
 * 구간 한 줄의 표기. (TP-216)
 *
 * **이동수단을 화면에서 정하지 않는다.** 예전에는 "도보 이동 약 N분"으로 고정
 * 표기했는데, 도보 예상시간이 임계값을 넘는 구간은 서버가 대중교통으로 전환한다
 * (tools/schedule_travel._select_mode) — 4.3km 61분 구간이 화면에는 도보로 떴다.
 * 서버가 내려준 travel_to_next_mode를 그대로 쓴다.
 *
 * **추천 카드와 규칙이 다르다.** 추천 카드는 실측이 없으면 시간을 아예 말하지
 * 않고 직선거리만 말한다(utils/travelDisplay.ts). 일정은 이동시간 없이 성립하지
 * 않으므로 값을 보여주고 추정임을 함께 밝힌다.
 *
 * 이동수단이 없는 구간은 서버가 좌표를 못 구해 시간표 폴백값(15분)을 쓴
 * 자리다. 근거가 없으므로 수단도 실측 여부도 말하지 않는다.
 */
export function scheduleTravelLabel(
  minutes: number,
  mode: TravelMode | null | undefined,
  measured: boolean | undefined,
): string {
  if (!mode) {
    return `이동 약 ${minutes}분`;
  }
  return `${MODE_LABEL[mode]} ${minutes}분${measured ? "" : " · 추정"}`;
}

/**
 * 추정 구간에 붙는 설명. 왜 실측이 아닌지(어느 API가 실패했는지)까지는 말하지 않는다.
 *
 * 한 문장으로 둔다 — 두 문장이던 것이 "…예상값이에요. …구간입니다."로 문체가 섞여
 * 있었다.
 */
export const SCHEDULE_TRAVEL_ESTIMATE_HINT =
  "실제 경로를 못 불러와서 직선거리로 어림한 시간이에요.";

/**
 * 두 정류장이 같은 묶음인가. (TP-243)
 *
 * **묶음은 자리가 아니라 구간의 성질이라 여기서 판정한다.** "가까이 붙어 있다"는
 * 두 곳 사이의 이야기이고, 화면에서도 카드가 아니라 카드 사이 이동 줄에 붙는다.
 * 채팅 타임라인과 일정 화면이 같은 규칙을 쓰게 하려고 한 곳에 둔다.
 *
 * 번호가 없는 옛 스냅샷은 항상 false다 — 묶음 표시가 없을 뿐 화면은 그대로다.
 */
export function isSameCluster(from: ScheduleItem, to: ScheduleItem): boolean {
  const id = from.cluster_id;
  return id !== null && id !== undefined && id === to.cluster_id;
}

/** 묶인 구간의 이동 줄에 덧붙이는 말. 앞의 이동 표기에 " · "로 잇는다. */
export const SCHEDULE_CLUSTER_NOTE = "이어서 둘러보기";
export const SCHEDULE_CLUSTER_NOTE_EN = "nearby stop";
