/*
 * 역할: 일정 편성 API 응답을 채팅 메시지 안에서 세로 타임라인으로 렌더링한다.
 * 입력: ScheduleResult(items/route_summary/total_duration_min/basis_note),
 *   재조정·검색 범위 확대 콜백, 로딩 상태.
 * 출력: 정류장(ScheduleCard)과 이동 구간(ScheduleTravelSegment)이 번갈아
 *   이어지는 타임라인, 근거 시각 안내, "다른 코스 보기"/"검색 범위 넓혀서
 *   다시 찾기" 버튼. 총 소요 시간·동선 요약 문구는 여기서 만들지 않는다 —
 *   바로 위 assistant_text 말풍선(백엔드 compose_schedule_message)이 이미
 *   보여주고 있어서 중복 렌더링이었다(SCHEDULE-10 후속: 요청 시간과 실제
 *   편성 시간이 다를 때 "N분 코스를 짜봤어요"가 어색해 보이는 문제를 고치며
 *   같은 문구가 말풍선·카드 두 곳에서 각자 계산되고 있던 걸 발견해 정리함).
 * 호출 시점: ChatPage가 schedule_result 메시지를 렌더링할 때 호출된다.
 *
 * 재조정 버튼은 새 기능이 아니라 RECOMMEND가 이미 쓰던 것과 같은 문구를
 * 재사용한다(REQUEST_MORE_PROMPT="다른 곳 보여줘", RELAX_RADIUS_PROMPT="검색
 * 범위를 넓혀서 다시 추천해줘") — SCHEDULE-06이 last_intent="SCHEDULE"일 때
 * 이 문구들을 이미 재편성 경로로 라우팅하므로 백엔드 변경 없이 버튼만 잇는다
 * (SCHEDULE-08).
 *
 * showElapsedTime이 true면(개발자 화면) 지연시간을 보여준다 — RecommendationResultMessage와
 * 같은 방식이다. ScheduleResult.elapsed_ms(planner.py plan_schedule()/
 * plan_partial_schedule()이 측정)를 서버 소요로, elapsedMs를 클라이언트 소요로 쓴다.
 */

import type { ScheduleResult } from "../../types";
import { ScheduleCard } from "../ScheduleCard";
import { ScheduleTravelSegment } from "../ScheduleTravelSegment";
import { FeedbackButtons } from "./FeedbackButtons";

function formatDuration(milliseconds: number | undefined) {
  if (typeof milliseconds !== "number" || !Number.isFinite(milliseconds)) return "-";
  return milliseconds >= 1000
    ? `${(milliseconds / 1000).toFixed(1)}초`
    : `${Math.round(milliseconds)}ms`;
}

interface ScheduleResultMessageProps {
  schedule: ScheduleResult;
  elapsedMs?: number;
  showElapsedTime?: boolean;
  isLoading: boolean;
  onRequestMore: () => void;
  onRelaxRadius: () => void;
  sessionId: string;
  runId: string;
  /** 피드백 전송용. ChatMessageList가 근처 메시지에서 찾아 넘겨준다(선택 사항). */
  userInput?: string;
  assistantMessage?: string;
  intent?: string;
}

export function ScheduleResultMessage({
  schedule,
  elapsedMs,
  showElapsedTime = false,
  isLoading,
  onRequestMore,
  onRelaxRadius,
  sessionId,
  runId,
  userInput,
  assistantMessage,
  intent,
}: ScheduleResultMessageProps) {
  const hasItems = schedule.items.length > 0;

  return (
    <article className="mr-auto flex w-full max-w-2xl flex-col gap-4 rounded-md border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      {/* 총 소요 시간·동선 요약은 바로 위 assistant_text 말풍선(compose_schedule_message)이
          이미 보여주므로 여기서 다시 반복하지 않는다 — 카드는 타임라인/액션만 맡는다. */}
      {showElapsedTime && (
        <p className="text-right text-xs text-gray-500 dark:text-gray-400">
          {formatDuration(elapsedMs)} 소요 (서버 {formatDuration(schedule.elapsed_ms)})
        </p>
      )}
      <FeedbackButtons
        sessionId={sessionId}
        runId={runId}
        userInput={userInput}
        assistantMessage={assistantMessage}
        intent={intent}
      />
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
