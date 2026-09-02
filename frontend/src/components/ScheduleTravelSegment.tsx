/*
 * 역할: 타임라인에서 정류장(ScheduleCard) 사이의 이동 구간을 표시한다.
 * 입력: 다음 장소까지 이동 시간(분), 이동수단, 그 값이 실측인지 여부.
 * 출력: 세로선이 이어지는 좁은 구간에 "대중교통 이동 20분" 같은 텍스트.
 * 호출 시점: ScheduleResultMessage가 item.travel_to_next_min이 있는 항목
 *   뒤에(=마지막 항목이 아닐 때) 렌더링한다.
 *
 * 표기 규칙 자체는 utils/scheduleTravel.ts에 있다 — SchedulePage(전용 시트
 * 레이아웃)와 개발자 감사 패널이 같은 문구를 쓰는데, 이 파일에서 함수까지
 * 내보내면 fast refresh가 깨진다(react-refresh/only-export-components).
 */

import { scheduleTravelLabel, SCHEDULE_TRAVEL_ESTIMATE_HINT } from "../utils/scheduleTravel";
import type { TravelMode } from "../types";

interface ScheduleTravelSegmentProps {
  minutes: number;
  mode?: TravelMode | null;
  measured?: boolean;
}

export function ScheduleTravelSegment({ minutes, mode, measured }: ScheduleTravelSegmentProps) {
  return (
    <li className="flex gap-3">
      <div className="flex w-7 shrink-0 justify-center">
        <span className="h-4 w-px bg-border" />
      </div>
      <p
        className="flex flex-1 items-center pb-2 text-[11px] text-muted"
        title={measured ? undefined : SCHEDULE_TRAVEL_ESTIMATE_HINT}
      >
        {scheduleTravelLabel(minutes, mode, measured)}
      </p>
    </li>
  );
}
