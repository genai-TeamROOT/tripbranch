/*
 * 역할: 지금 세션에서 마지막으로 짠 일정을 보여준다. Figma "Schedule (Sheet)"
 *   (29:82) 화면 그대로 옮긴 것이다.
 * 입력: TripContext의 messages 중 가장 최근 schedule_result.
 * 출력: 요약 문구, 정류장 타임라인(장소 상세는 기존 RecommendationDetailPreviewModal
 *   재사용), 도움이 됐는지 피드백(로컬 표시만 — 세션/런 id가 이 메시지에 없어
 *   실제 전송은 안 한다), 없으면 홈으로 돌아가 다시 물어보라는 안내.
 * 호출 시점: 사이드바 "일정"에서 바텀시트로 열린다(DESIGN_SYSTEM.md §5).
 *
 * 카드 레이아웃은 ChatMessageList가 쓰는 ScheduleCard/ScheduleTravelSegment와
 * 다르다 — 그 둘은 대화 중 짧게 보여주는 용도로 이미 확정돼 있고(Phase 4/5),
 * 이 화면은 Figma가 별도로 그린 전용 시트 레이아웃(이미지+도착 배지를 카드
 * 안에 함께 두는 방식)이라 여기서만 따로 그린다.
 */

import { ChevronRight, Route as RouteIcon, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/layout/AppHeader";
import { RecommendationDetailPreviewModal } from "../components/chat/RecommendationDetailPreviewModal";
import { useTripState } from "../state/TripContext";
import type { ScheduleItem } from "../types";
import { scheduleTravelLabel } from "../utils/scheduleTravel";

function ScheduleStop({ item, isLast }: { item: ScheduleItem; isLast: boolean }) {
  const [showDetail, setShowDetail] = useState(false);

  return (
    <li className="flex gap-3">
      <div className="flex w-7 shrink-0 flex-col items-center gap-1">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-[11px] font-bold text-white">
          {item.order}
        </span>
        {!isLast && <span className="w-px flex-1 bg-border" />}
      </div>

      <div
        className={`flex flex-1 gap-3 rounded-2xl bg-white p-3 shadow-resting ${isLast ? "" : "mb-5"}`}
      >
        <div className="flex w-20 shrink-0 flex-col items-center gap-1">
          <span className="flex h-20 w-20 items-center justify-center rounded-xl bg-chip text-muted">
            <RouteIcon size={20} />
          </span>
          <span className="rounded-full bg-chip px-2 py-0.5 text-[11px] font-bold text-brand">
            {item.estimated_arrival} 도착
          </span>
          {/* break-keep — 이 칸이 w-20(80px)이라 "대중교통 이동 17분 · 추정"이 두 줄로
              접히는데, 그대로 두면 "17" / "분"이나 "추" / "정" 사이가 끊긴다(TP-216). */}
          {item.travel_to_next_min !== null && (
            <span className="break-keep text-center text-[11px] leading-tight text-muted">
              {scheduleTravelLabel(
                item.travel_to_next_min,
                item.travel_to_next_mode,
                item.travel_to_next_measured,
              )}
            </span>
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="truncate text-sm font-bold text-ink">{item.place_name}</p>
          <p className="text-xs leading-relaxed text-muted">{item.reason}</p>
          <p className="text-xs text-ink">
            머무는 시간 <span className="font-medium">{item.estimated_duration_min}분</span>
          </p>
          {item.warnings != null && item.warnings.length > 0 && (
            <p className="text-[11px] text-gold">{item.warnings.join(" / ")}</p>
          )}
          <button
            type="button"
            onClick={() => setShowDetail(true)}
            className="mt-0.5 flex items-center gap-0.5 text-[11px] font-bold text-brand"
          >
            장소 상세보기 <ChevronRight size={11} />
          </button>
        </div>
      </div>

      {showDetail && (
        <RecommendationDetailPreviewModal
          placeId={item.place_id}
          placeName={item.place_name}
          onClose={() => setShowDetail(false)}
        />
      )}
    </li>
  );
}

export function SchedulePage() {
  const navigate = useNavigate();
  const state = useTripState();
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);

  const lastSchedule = [...state.messages]
    .reverse()
    .find((message) => message.type === "schedule_result");

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader onBack={() => navigate(-1)} />
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-5 px-4 pb-10">
        {!lastSchedule || lastSchedule.schedule.items.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-chip text-brand">
              <RouteIcon size={22} />
            </span>
            <p className="text-sm text-muted">아직 짠 일정이 없어요.</p>
            <button
              type="button"
              onClick={() => navigate("/")}
              className="rounded-full bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-deep active:scale-[0.98]"
            >
              홈에서 일정 짜기
            </button>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-1.5 rounded-2xl bg-sky-light p-4">
              <p className="text-xs font-bold text-brand-deep">
                {new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}{" "}
                기준으로 짠 동선이에요
              </p>
              <p className="text-sm leading-relaxed text-ink">
                {lastSchedule.schedule.route_summary}
              </p>
            </div>

            <ul className="flex flex-col">
              {lastSchedule.schedule.items.map((item, index) => (
                <ScheduleStop
                  key={item.place_id}
                  item={item}
                  isLast={index === lastSchedule.schedule.items.length - 1}
                />
              ))}
            </ul>

            <div className="flex items-center gap-2">
              <p className="text-[11px] text-muted">이 일정이 도움이 됐나요?</p>
              <button
                type="button"
                aria-label="도움이 됐어요"
                aria-pressed={feedback === "up"}
                onClick={() => setFeedback((prev) => (prev === "up" ? null : "up"))}
                className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                  feedback === "up" ? "bg-brand text-white" : "bg-chip text-muted hover:text-brand"
                }`}
              >
                <ThumbsUp size={13} />
              </button>
              <button
                type="button"
                aria-label="도움이 안 됐어요"
                aria-pressed={feedback === "down"}
                onClick={() => setFeedback((prev) => (prev === "down" ? null : "down"))}
                className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                  feedback === "down" ? "bg-rust text-white" : "bg-chip text-muted hover:text-rust"
                }`}
              >
                <ThumbsDown size={13} />
              </button>
            </div>

            {lastSchedule.schedule.basis_note && (
              <p className="rounded-xl bg-chip px-3 py-2.5 text-[11px] leading-relaxed text-muted">
                {lastSchedule.schedule.basis_note}
              </p>
            )}

            <button
              type="button"
              onClick={() => navigate("/")}
              className="flex h-12 w-full items-center justify-center rounded-full bg-white text-sm font-bold text-brand shadow-resting"
            >
              홈에서 다시 물어보기
            </button>
          </>
        )}
      </div>
    </main>
  );
}
