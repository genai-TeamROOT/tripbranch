/*
 * 역할: 일정 편성 API 응답을 채팅 메시지 안에서 세로 타임라인으로 렌더링한다.
 * 입력: ScheduleResult(items/route_summary/total_duration_min/basis_note),
 *   재조정·검색 범위 확대 콜백, 로딩 상태.
 * 출력: 동선 요약, 총 소요 시간, 정류장(ScheduleCard)과 이동 구간
 *   (ScheduleTravelSegment)이 번갈아 이어지는 타임라인, 근거 시각 안내,
 *   "다른 코스 보기"/"검색 범위 넓혀서 다시 찾기" 버튼.
 * 호출 시점: ChatPage가 schedule_result 메시지를 렌더링할 때 호출된다.
 *
 * 재조정 버튼은 새 기능이 아니라 RECOMMEND가 이미 쓰던 것과 같은 문구를
 * 재사용한다(REQUEST_MORE_PROMPT="다른 곳 보여줘", RELAX_RADIUS_PROMPT="검색
 * 범위를 넓혀서 다시 추천해줘") — SCHEDULE-06이 last_intent="SCHEDULE"일 때
 * 이 문구들을 이미 재편성 경로로 라우팅하므로 백엔드 변경 없이 버튼만 잇는다
 * (SCHEDULE-08).
 */

import type { ScheduleResult } from "../../types";
import { ScheduleCard } from "../ScheduleCard";
import { ScheduleTravelSegment } from "../ScheduleTravelSegment";

interface ScheduleResultMessageProps {
  schedule: ScheduleResult;
  isLoading: boolean;
  onRequestMore: () => void;
  onRelaxRadius: () => void;
}

function formatTotalDuration(totalMinutes: number) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours <= 0) return `${minutes}분`;
  if (minutes <= 0) return `${hours}시간`;
  return `${hours}시간 ${minutes}분`;
}

export function ScheduleResultMessage({
  schedule,
  isLoading,
  onRequestMore,
  onRelaxRadius,
}: ScheduleResultMessageProps) {
  const hasItems = schedule.items.length > 0;

  return (
    <article className="mr-auto flex w-full max-w-2xl flex-col gap-4 rounded-md border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="flex flex-col gap-1">
        {hasItems && (
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
            {formatTotalDuration(schedule.total_duration_min)} 코스를 짜봤어요.
          </p>
        )}
        <p className="text-sm text-gray-600 dark:text-gray-400">{schedule.route_summary}</p>
      </div>

      {hasItems ? (
        <>
          <section className="flex flex-col gap-3">
            <h3 className="text-sm font-semibold text-gray-500 dark:text-gray-400">일정</h3>
            <ul className="flex flex-col">
              {schedule.items.flatMap((item, index) => {
                const nodes = [
                  <ScheduleCard
                    key={item.place_id}
                    item={item}
                    isLast={index === schedule.items.length - 1}
                  />,
                ];
                if (item.travel_to_next_min !== null) {
                  nodes.push(
                    <ScheduleTravelSegment
                      key={`${item.place_id}-travel`}
                      minutes={item.travel_to_next_min}
                    />,
                  );
                }
                return nodes;
              })}
            </ul>
          </section>

          {schedule.basis_note && (
            <p className="rounded bg-gray-50 px-3 py-2 text-xs text-gray-500 dark:bg-gray-800 dark:text-gray-400">
              {schedule.basis_note}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={isLoading}
              onClick={onRequestMore}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium disabled:opacity-50 dark:border-gray-700"
            >
              {isLoading ? "불러오는 중..." : "다른 코스 보기"}
            </button>
            <span className="self-center text-xs text-gray-500 dark:text-gray-400">
              다른 조건이 있으면 아래 입력창에 이어서 적어주세요.
            </span>
          </div>
        </>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <button
            type="button"
            disabled={isLoading}
            onClick={onRelaxRadius}
            className="w-fit rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
          >
            검색 범위 넓혀서 다시 찾기
          </button>
        </div>
      )}
    </article>
  );
}
