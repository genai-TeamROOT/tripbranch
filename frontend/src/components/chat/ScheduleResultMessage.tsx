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

import { useState } from "react";
import { saveSchedule } from "../../api/trip";
import { refreshSavedSchedules } from "../../state/savedSchedules";
import type { ScheduleResult } from "../../types";
import { defaultScheduleTitle } from "../../utils/scheduleTitle";
import { ScheduleCard } from "../ScheduleCard";
import { ScheduleTravelSegment } from "../ScheduleTravelSegment";

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
  /* 저장에 함께 보낸다. run_id는 같은 턴을 두 번 저장하지 않기 위한 열쇠이고
     session_id는 출처 표시다. 응답이 run_id 없이 끝나는 경로가 있어 둘 다 선택. */
  runId?: string;
  sessionId?: string;
}

/* idle → saving → saved. 실패는 error로 빠지고 다시 누를 수 있다. */
type SaveState = "idle" | "saving" | "saved" | "error";

export function ScheduleResultMessage({
  schedule,
  elapsedMs,
  showElapsedTime = false,
  isLoading,
  onRequestMore,
  onRelaxRadius,
  runId,
  sessionId,
}: ScheduleResultMessageProps) {
  const hasItems = schedule.items.length > 0;
  const [saveState, setSaveState] = useState<SaveState>("idle");

  /*
   * 저장은 낙관적으로 그리지 않는다. 보관함 담기와 달리 이건 목록에 새 줄을
   * 만드는 동작이라, 실패했는데 저장된 것처럼 보이면 사용자가 나중에 목록에서
   * 찾다가 없는 것을 겪는다.
   */
  async function handleSave() {
    if (saveState === "saving" || saveState === "saved") return;
    setSaveState("saving");
    try {
      await saveSchedule({
        title: defaultScheduleTitle(schedule.items),
        payload: schedule,
        sessionId,
        runId,
      });
      setSaveState("saved");
      /* 사이드바 목록을 바로 갱신한다. 저장하고 사이드바를 봤는데 없으면
         사용자는 저장이 안 된 줄 안다 — 실제로 새로고침해야 보였다. */
      void refreshSavedSchedules();
    } catch {
      setSaveState("error");
    }
  }

  return (
    <article className="mr-auto flex w-full flex-col gap-3.5">
      {/* 총 소요 시간·동선 요약은 바로 위 assistant_text 말풍선(compose_schedule_message)이
          이미 보여주므로 여기서 다시 반복하지 않는다 — 카드는 타임라인/액션만 맡는다. */}
      {showElapsedTime && (
        <p className="text-right text-xs text-muted">
          {formatDuration(elapsedMs)} 소요 (서버 {formatDuration(schedule.elapsed_ms)})
        </p>
      )}
      {hasItems ? (
        <>
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
                    mode={item.travel_to_next_mode}
                    measured={item.travel_to_next_measured}
                  />,
                );
              }
              return nodes;
            })}
          </ul>

          {schedule.basis_note && (
            <p className="rounded-xl bg-chip px-3 py-2.5 text-[11px] leading-relaxed text-muted">
              {schedule.basis_note}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={isLoading}
              onClick={onRequestMore}
              className="rounded-full border border-border bg-white px-4 py-2.5 text-sm font-medium text-ink transition-colors hover:border-brand hover:text-brand disabled:opacity-50"
            >
              {isLoading ? "불러오는 중..." : "다른 코스 보기"}
            </button>
            {/*
              같은 턴을 두 번 저장해도 서버가 한 줄로 받지만(멱등), 버튼을 잠가
              사용자가 "눌렸나?" 하고 다시 누르지 않게 한다.
            */}
            <button
              type="button"
              disabled={saveState === "saving" || saveState === "saved"}
              onClick={() => void handleSave()}
              className="rounded-full border border-border bg-white px-4 py-2.5 text-sm font-medium text-ink transition-colors hover:border-brand hover:text-brand disabled:opacity-50"
            >
              {saveState === "saved"
                ? "저장했어요"
                : saveState === "saving"
                  ? "저장하는 중..."
                  : "이 일정 저장"}
            </button>
            {saveState === "error" ? (
              <span role="alert" className="text-xs text-rust">
                저장하지 못했어요. 다시 눌러주세요.
              </span>
            ) : (
              <span className="text-xs text-muted">
                다른 조건이 있으면 아래 입력창에 이어서 적어주세요.
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <button
            type="button"
            disabled={isLoading}
            onClick={onRelaxRadius}
            className="w-fit rounded-full bg-rust px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-rust/90 active:scale-[0.98] disabled:opacity-50"
          >
            검색 범위 넓혀서 다시 찾기
          </button>
        </div>
      )}
    </article>
  );
}
