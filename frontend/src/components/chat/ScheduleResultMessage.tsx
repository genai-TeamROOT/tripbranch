/*
 * 역할: 일정 편성 API 응답을 채팅 메시지 안에서 순서 카드 목록으로 렌더링한다.
 * 입력: ScheduleResult(items/route_summary/total_duration_min/basis_note).
 * 출력: 동선 요약, 총 소요 시간, 근거 시각 안내, ScheduleCard 목록.
 * 호출 시점: ChatPage가 schedule_result 메시지를 렌더링할 때 호출된다.
 * TODO: 일정 재조정("다른 데로 바꿔줘") 액션이 생기면 버튼을 추가한다.
 */

import type { ScheduleResult } from "../../types";
import { ScheduleCard } from "../ScheduleCard";

interface ScheduleResultMessageProps {
  schedule: ScheduleResult;
}

function formatTotalDuration(totalMinutes: number) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours <= 0) return `${minutes}분`;
  if (minutes <= 0) return `${hours}시간`;
  return `${hours}시간 ${minutes}분`;
}

export function ScheduleResultMessage({ schedule }: ScheduleResultMessageProps) {
  return (
    <article className="mr-auto flex w-full max-w-2xl flex-col gap-4 rounded-md border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
          {formatTotalDuration(schedule.total_duration_min)} 코스를 짜봤어요.
        </p>
        <p className="text-sm text-gray-600 dark:text-gray-400">{schedule.route_summary}</p>
      </div>

      {schedule.items.length > 0 && (
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold text-gray-500 dark:text-gray-400">일정</h3>
          <ul className="flex flex-col gap-3">
            {schedule.items.map((item) => (
              <ScheduleCard key={item.place_id} item={item} />
            ))}
          </ul>
        </section>
      )}

      {schedule.basis_note && (
        <p className="rounded bg-gray-50 px-3 py-2 text-xs text-gray-500 dark:bg-gray-800 dark:text-gray-400">
          {schedule.basis_note}
        </p>
      )}
    </article>
  );
}
