import { useEffect, useState } from "react";

const AGENT_STAGES = [
  { label: "요청 의도와 조건 파악", detail: "Gemini가 Intent와 사용자 조건을 해석하고 있어요." },
  { label: "대화 조건 병합", detail: "이전 대화와 이번 요청의 조건을 합치고 있어요." },
  { label: "장소 정보 조회", detail: "위치·날씨·운영시간에 맞는 후보를 찾고 있어요." },
  { label: "추천 순위 계산", detail: "조건별 점수를 계산해 장소의 순서를 정하고 있어요." },
  { label: "답변 정리", detail: "추천 결과와 안내 문구를 정리하고 있어요." },
] as const;

const STAGE_INTERVAL_MS = 1800;

export function AgentProgressMessage({ hasDeviceLocation }: { hasDeviceLocation: boolean }) {
  const [stageIndex, setStageIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setStageIndex((current) => Math.min(current + 1, AGENT_STAGES.length - 1));
    }, STAGE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const current = AGENT_STAGES[stageIndex];

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
        </div>
      </div>

      <ol className="mt-4 grid gap-2 text-xs">
        <li className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
          <span aria-hidden="true">✓</span>
          {hasDeviceLocation ? "기기 위치 확인 완료" : "입력 위치 기준으로 진행"}
        </li>
        {AGENT_STAGES.map((stage, index) => {
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
