/*
 * 역할: 지금 세션에서 마지막으로 짠 일정을 보여준다.
 * 입력: TripContext의 messages 중 가장 최근 schedule_result.
 * 출력: 그 일정의 타임라인(읽기 전용), 없으면 채팅으로 돌아가 짜자는 안내.
 * 호출 시점: 사이드바 "일정"에서 바텀시트로 열린다(DESIGN_SYSTEM.md §5).
 *
 * 일정은 세션에만 남는다 — 새로고침하면 사라지는 messages 배열이 유일한 저장소라
 * (state/TripContext.tsx), 별도로 저장하거나 지난 세션 일정을 불러오는 기능은
 * 없다. "다른 코스 보기"·"검색 범위 넓히기" 같은 재요청 버튼은 ChatPage의 채팅
 * 흐름에 물려 있어 여기서는 다시 만들지 않고, 그 대신 채팅으로 돌아가는 길만 안내한다.
 */

import { Route as RouteIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/layout/AppHeader";
import { ScheduleCard } from "../components/ScheduleCard";
import { ScheduleTravelSegment } from "../components/ScheduleTravelSegment";
import { useTripState } from "../state/TripContext";

export function SchedulePage() {
  const navigate = useNavigate();
  const state = useTripState();

  const lastSchedule = [...state.messages]
    .reverse()
    .find((message) => message.type === "schedule_result");

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader onBack={() => navigate(-1)} />
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-3.5 px-4 pb-10">
        <h1 className="text-[24px] font-bold leading-snug text-ink">일정</h1>

        {!lastSchedule || lastSchedule.schedule.items.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-chip text-brand">
              <RouteIcon size={22} />
            </span>
            <p className="text-sm text-muted">아직 짠 일정이 없어요.</p>
            <button
              type="button"
              onClick={() => navigate("/chat")}
              className="rounded-full bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-deep active:scale-[0.98]"
            >
              채팅에서 일정 짜기
            </button>
          </div>
        ) : (
          <>
            <ul className="flex flex-col">
              {lastSchedule.schedule.items.flatMap((item, index) => {
                const nodes = [
                  <ScheduleCard
                    key={item.place_id}
                    item={item}
                    isLast={index === lastSchedule.schedule.items.length - 1}
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
            {lastSchedule.schedule.basis_note && (
              <p className="rounded-xl bg-chip px-3 py-2.5 text-[11px] leading-relaxed text-muted">
                {lastSchedule.schedule.basis_note}
              </p>
            )}
          </>
        )}
      </div>
    </main>
  );
}
