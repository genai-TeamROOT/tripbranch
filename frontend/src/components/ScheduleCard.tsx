/*
 * 역할: 일정에 포함된 장소 하나를 순서 카드 형태로 렌더링한다.
 * 입력: ScheduleItem 데이터.
 * 출력: 순서 번호, 장소명, 도착 시각, 머무는 시간, 배치 이유 UI.
 * 호출 시점: ScheduleResultMessage가 일정 항목 목록을 표시할 때 호출된다.
 * TODO: 지도 링크, 카드 재배치 액션이 생기면 하위 UI를 확장한다.
 */

import type { ScheduleItem } from "../types";

interface ScheduleCardProps {
  item: ScheduleItem;
}

export function ScheduleCard({ item }: ScheduleCardProps) {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-gray-200 p-4 shadow-sm dark:border-gray-700">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-semibold text-white dark:bg-gray-100 dark:text-gray-900">
            {item.order}
          </span>
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            {item.place_name}
          </h3>
        </div>
        <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-300">
          {item.estimated_arrival} 도착
        </span>
      </div>

      <p className="text-sm text-gray-600 dark:text-gray-400">{item.reason}</p>

      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-700 dark:text-gray-300">
        <div className="flex gap-1">
          <dt className="text-gray-400">머무는 시간</dt>
          <dd>{item.estimated_duration_min}분</dd>
        </div>
      </dl>

      {item.travel_to_next_min !== null && (
        <p className="pt-1 text-xs text-gray-400 dark:text-gray-500">
          다음 장소까지 이동 약 {item.travel_to_next_min}분
        </p>
      )}
    </li>
  );
}
