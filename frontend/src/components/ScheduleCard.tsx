/*
 * 역할: 일정에 포함된 장소 하나를 세로 타임라인의 한 정류장으로 렌더링한다(DESIGN_SYSTEM.md §6.7).
 * 입력: ScheduleItem 데이터, 마지막 정류장인지 여부(isLast).
 * 출력: 순서 배지 + 다음 정류장으로 이어지는 세로선(왼쪽), 도착 배지·장소명·배치
 *   이유·머무는 시간(오른쪽 카드). 정류장 사이 이동 시간은 이 컴포넌트가 아니라
 *   ScheduleTravelSegment가 표시한다 — 카드는 "머무는 곳"만, 이동은 카드 사이
 *   별도 구간으로 분리한다(SCHEDULE-08).
 * 호출 시점: ScheduleResultMessage가 일정 항목 목록을 표시할 때 호출된다.
 * TODO: 지도 링크, 카드 재배치 액션이 생기면 하위 UI를 확장한다.
 */

import type { ScheduleItem } from "../types";

interface ScheduleCardProps {
  item: ScheduleItem;
  isLast: boolean;
}

export function ScheduleCard({ item, isLast }: ScheduleCardProps) {
  return (
    <li className="flex gap-3">
      <div className="flex w-7 shrink-0 flex-col items-center">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-bold text-white">
          {item.order}
        </span>
        {!isLast && <span className="mt-1 w-px flex-1 bg-border" />}
      </div>

      <div
        className={`flex flex-1 flex-col gap-2 rounded-2xl bg-white p-3.5 shadow-resting ${isLast ? "" : "mb-3.5"}`}
      >
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-bold text-ink">{item.place_name}</h3>
          <span className="shrink-0 rounded-full bg-chip px-2 py-0.5 text-[11px] font-semibold text-brand">
            {item.estimated_arrival} 도착
          </span>
        </div>

        <p className="text-xs leading-relaxed text-muted">{item.reason}</p>

        <p className="text-xs text-ink/70">
          머무는 시간{" "}
          <span className="font-semibold text-ink">{item.estimated_duration_min}분</span>
        </p>

        {/* estimated_arrival이 이 장소의 운영시간과 어긋날 때 planner.py가
            구조적으로 채우는 경고 — LLM이 아니라 시스템이 결정적으로 판단한
            값이다(docs/design/int-07-schedule.md v2.2, "폐점 스탑 감지"). */}
        {item.warnings != null && item.warnings.length > 0 && (
          <p className="rounded-lg bg-gold-tint px-2 py-1 text-xs text-ink">
            ⚠️ {item.warnings.join(" / ")}
          </p>
        )}
      </div>
    </li>
  );
}
