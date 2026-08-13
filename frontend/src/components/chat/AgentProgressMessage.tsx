import { useEffect, useState } from "react";

const AGENT_STAGES = [
  { stage: "interpreting", label: "요청 의도와 조건 파악", detail: "Gemini가 Intent와 사용자 조건을 해석하고 있어요." },
  { stage: "merging_conditions", label: "대화 조건 병합", detail: "이전 대화 조건을 반영하고 있어요." },
  { stage: "fetching_context", label: "장소 정보 조회", detail: "장소·운영시간·날씨 정보를 찾고 있어요." },
  { stage: "scoring", label: "추천 순위 계산", detail: "조건에 맞게 장소 순위를 계산하고 있어요." },
  { stage: "composing_message", label: "답변 정리", detail: "추천 결과를 안내하고 있어요." },
] as const;

const SCHEDULE_STAGE = {
  stage: "scheduling",
  label: "일정 편성",
  detail: "장소 순서와 머무는 시간을 구성하고 있어요.",
} as const;

// 실제 서버 단계는 응답이 끝난 뒤 개발자 Audit의 소요시간 탭에서 정확히 확인한다.
// 채팅 로딩 UI는 특정 외부 호출(특히 LLM)에서 수 초간 멈춘 인상을 주지 않도록
// 순차적으로 움직인다. 모든 단계를 한 번 보여준 뒤에는 마지막 단계에 머문다.
const STAGE_ROTATION_INTERVAL_MS = 1_700;
const ELAPSED_REFRESH_INTERVAL_MS = 100;

export function AgentProgressMessage({
  hasDeviceLocation,
  schedulePlanning = false,
}: {
  hasDeviceLocation: boolean;
  /** 실제 SCHEDULE 플래너 호출 이벤트를 받은 뒤에만 일정 단계를 목록에 넣는다. */
  schedulePlanning?: boolean;
}) {
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    const startedAt = performance.now();
    const timer = window.setInterval(() => {
      setElapsedMs(performance.now() - startedAt);
    }, ELAPSED_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const stages = schedulePlanning
    ? [...AGENT_STAGES.slice(0, -1), SCHEDULE_STAGE, AGENT_STAGES.at(-1)!]
    : AGENT_STAGES;
  const stageIndex = Math.min(
    Math.floor(elapsedMs / STAGE_ROTATION_INTERVAL_MS),
    stages.length - 1,
  );
  const current = stages[stageIndex];

  return (
    <section
      role="status"
      aria-live="polite"
      className="mr-auto w-full max-w-xl rounded-xl border border-indigo-200 bg-indigo-50/80 p-4 text-sm text-indigo-950 shadow-sm dark:border-indigo-800 dark:bg-indigo-950/30 dark:text-indigo-100"
    >
      <div className="flex items-center gap-3">
        <span className="relative flex h-3 w-3" aria-hidden="true">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-60" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-indigo-600 dark:bg-indigo-300" />
        </span>
        <div>
          <p className="font-semibold">{current.label} 중</p>
          <p className="mt-0.5 text-xs text-indigo-700 dark:text-indigo-300">{current.detail}</p>
          <p className="mt-0.5 text-xs text-indigo-600 dark:text-indigo-400">
            {(elapsedMs / 1000).toFixed(1)}초 경과
          </p>
        </div>
      </div>

      <ol className="mt-4 grid gap-2 text-xs">
        <li className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
          <span aria-hidden="true">✓</span>
          {hasDeviceLocation ? "기기 위치 확인 완료" : "입력 위치 기준으로 진행"}
        </li>
        {stages.map((stage, index) => {
          const complete = index < stageIndex;
          const active = index === stageIndex;
          return (
            <li
              key={stage.label}
              className={`flex items-center gap-2 ${
                active
                  ? "font-semibold text-indigo-900 dark:text-indigo-100"
                  : complete
                    ? "text-emerald-700 dark:text-emerald-300"
                    : "text-gray-400 dark:text-gray-600"
              }`}
            >
              <span aria-hidden="true">{complete ? "✓" : active ? "●" : "○"}</span>
              {stage.label}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
