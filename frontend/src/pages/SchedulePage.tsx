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

import { Route as RouteIcon, ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AppHeader } from "../components/layout/AppHeader";
import { useTripState } from "../state/TripContext";
import { fetchSavedSchedule } from "../api/trip";
import { SavedScheduleList } from "../components/schedule/SavedScheduleList";
import { useSavedSchedules } from "../hooks/useSavedSchedules";
import { ScheduleRibbon } from "../components/schedule/ScheduleRibbon";
import { ScheduleRoute } from "../components/schedule/ScheduleRoute";
import { buildScheduleTimeline, clockLabel, locateNow } from "../utils/scheduleTimeline";
import type { SavedScheduleDetail } from "../types";

export function SchedulePage() {
  const navigate = useNavigate();
  const state = useTripState();
  const isEn = state.language === "en";
  const [searchParams] = useSearchParams();
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  /* 저장 목록이 비었는지는 빈 화면에서 무엇을 안내할지 정하는 데 쓴다.
     아직 못 받아온 동안(null)에는 안내를 띄우지 않는다 — 저장한 일정이 있는
     사람에게 "아직 짠 일정이 없어요"가 잠깐 스쳤다 사라지면 안 된다. */
  const savedList = useSavedSchedules();

  /*
   * ?saved=<id>로 들어오면 저장한 일정을 보여준다(SCHEDULE 카드 2). 없으면
   * 지금까지처럼 이번 세션의 마지막 일정을 보여준다.
   *
   * 저장한 일정을 여는 자리를 여기로 잡은 이유는 사이드바 "일정"이 이미 이
   * 화면을 열기 때문이다 — 목록에서 고른 일정이 다른 모양으로 열리면 같은
   * 것을 두 가지로 그리게 된다.
   */
  const savedId = searchParams.get("saved");
  const [saved, setSaved] = useState<SavedScheduleDetail | null>(null);
  const [savedError, setSavedError] = useState(false);

  useEffect(() => {
    if (!savedId) {
      setSaved(null);
      setSavedError(false);
      return;
    }
    let active = true;
    setSavedError(false);
    void fetchSavedSchedule(savedId)
      .then((detail) => {
        if (active) setSaved(detail);
      })
      .catch(() => {
        if (active) setSavedError(true);
      });
    return () => {
      active = false;
    };
  }, [savedId]);

  const lastSchedule = [...state.messages]
    .reverse()
    .find((message) => message.type === "schedule_result");

  /* 저장한 일정을 보고 있으면 그것이 화면의 일정이다. */
  const schedule = saved ? saved.payload : lastSchedule?.schedule;
  /*
   * **"언제 기준인지"를 지금 시각으로 쓰지 않는다.** 저장한 일정의 도착 시각·
   * 이동 시간은 저장 시점 값이라, 지금 시각을 얹으면 사흘 전 일정이 방금 짠
   * 것처럼 보인다.
   */
  const basisAt = saved ? new Date(saved.created_at) : new Date();

  /*
   * 머리말·띠에 쓸 값. 항목이 없거나 도착 시각을 못 읽으면 전부 null 이고, 그때는
   * 머리말이 route_summary 로 떨어진다 — 못 읽은 시각을 지어내지 않는다.
   *
   * "지금"은 저장한 일정에 얹지 않는다(basisAt 주석과 같은 이유).
   */
  const timeline = schedule ? buildScheduleTimeline(schedule.items) : null;
  const endLabel = timeline ? clockLabel(timeline.endMinutes, isEn) : null;
  const nowPosition = timeline && !saved ? locateNow(timeline, new Date()) : null;

  /* 예전 머리말이던 "몇 시 기준" 문장. 결정에 쓰이는 값이 아니라 근거 문단으로 내렸다. */
  const basisLine = saved
    ? isEn
      ? `Saved on ${basisAt.toLocaleDateString("en-US", { month: "long", day: "numeric" })}.`
      : `${basisAt.toLocaleDateString("ko-KR", { month: "long", day: "numeric" })}에 저장한 일정이에요.`
    : isEn
      ? `Planned as of ${basisAt.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}.`
      : `${basisAt.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })} 기준으로 짠 동선이에요.`;

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader onBack={() => navigate(-1)} />
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-5 px-4 pb-10">
        {/*
          빈 화면·실패 화면의 블록에서 `flex-1 justify-center`를 뺐다. 아래에
          저장한 일정 목록이 붙은 뒤로는 중앙 블록이 화면을 다 차지해 **목록이
          스크롤 밖으로 밀렸다** — 목록이 가장 필요한 상태에서 안 보였다.
        */}
        {savedError ? (
          <div className="flex flex-col items-center gap-3 py-14 text-center">
            <p className="text-sm text-muted">
              {isEn ? "Couldn't load that schedule." : "그 일정을 불러오지 못했어요."}
            </p>
            <p className="text-xs text-muted">
              {isEn
                ? "It may have been deleted, or you may not have access."
                : "이미 지워졌거나 접근 권한이 없을 수 있어요."}
            </p>
          </div>
        ) : !schedule || schedule.items.length === 0 ? (
          /*
            **저장한 일정이 있으면 빈 안내를 띄우지 않는다.** 아래 저장 목록이 이미
            "여기서 무엇을 할 수 있는지"를 보여주고 있어서, 그 위에 "아직 짠 일정이
            없어요"까지 붙으면 비었다는 안내가 두 번이 된다. 목록을 아직 못 받아온
            동안(null)에도 띄우지 않는다 — 잠깐 스쳤다 사라진다.
          */
          savedList !== null && savedList.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-14 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-chip text-brand">
                <RouteIcon size={22} />
              </span>
              <p className="text-sm text-muted">
                {isEn ? "No schedule yet." : "아직 짠 일정이 없어요."}
              </p>
              <button
                type="button"
                onClick={() => navigate("/")}
                className="rounded-full bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-deep active:scale-[0.98]"
              >
                {isEn ? "Plan a schedule from home" : "홈에서 일정 짜기"}
              </button>
            </div>
          ) : null
        ) : (
          <>
            {/*
              머리말은 "언제 끝나는가"다. 남은 시간에 맞는지가 이 화면에서 사용자가
              내리는 결정이라 가장 먼저 온다. 예전에는 "몇 시 기준으로 짠 동선"이
              머리말이었는데, 그건 결정에 쓰이지 않는 값이라 근거 문단으로 내렸다.
            */}
            <div className="flex flex-col gap-1.5">
              <h2 className="text-2xl font-bold tracking-tight tabular-nums text-ink">
                {endLabel
                  ? isEn
                    ? `Ends at ${endLabel}`
                    : `${endLabel}에 끝나요`
                  : schedule.route_summary}
              </h2>
              {endLabel && (
                <p className="max-w-[44ch] text-sm leading-relaxed text-label">
                  {schedule.route_summary}
                </p>
              )}
            </div>

            <ScheduleRibbon items={schedule.items} isEn={isEn} now={saved ? null : new Date()} />

            <ScheduleRoute
              items={schedule.items}
              isEn={isEn}
              nowIndex={nowPosition?.itemIndex ?? null}
              minutesLeftHere={nowPosition?.minutesLeftHere ?? null}
            />

            <div className="flex items-center gap-2">
              <p className="text-[11px] text-muted">
                {isEn ? "Was this schedule helpful?" : "이 일정이 도움이 됐나요?"}
              </p>
              <button
                type="button"
                aria-label={isEn ? "Helpful" : "도움이 됐어요"}
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
                aria-label={isEn ? "Not helpful" : "도움이 안 됐어요"}
                aria-pressed={feedback === "down"}
                onClick={() => setFeedback((prev) => (prev === "down" ? null : "down"))}
                className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                  feedback === "down" ? "bg-rust text-white" : "bg-chip text-muted hover:text-rust"
                }`}
              >
                <ThumbsDown size={13} />
              </button>
            </div>

            <p className="rounded-xl bg-chip px-3 py-2.5 text-[11px] leading-relaxed text-muted">
              {basisLine}
              {schedule.basis_note ? ` ${schedule.basis_note}` : ""}
            </p>

            <button
              type="button"
              onClick={() => navigate("/")}
              className="flex h-12 w-full items-center justify-center rounded-full bg-white text-sm font-bold text-brand shadow-resting"
            >
              {isEn ? "Ask again from home" : "홈에서 다시 물어보기"}
            </button>
          </>
        )}

        {/*
          저장한 일정 목록은 **세 상태 모두**에 둔다(일정 없음 / 일정 있음 /
          `?saved=` 실패). 원래 사이드바에 있었는데, 일정 탭이 이미 있으니 목록도
          여기 있는 편이 맞다 — 특히 "아직 짠 일정이 없어요"와 불러오기 실패
          화면에서는 **다른 일정을 고를 유일한 입구**다.
        */}
        <SavedScheduleList />
      </div>
    </main>
  );
}
