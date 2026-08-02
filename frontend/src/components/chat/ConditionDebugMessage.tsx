/*
 * 역할: 개발 모드에서 사용자 입력 해석 결과를 채팅 메시지로 표시한다.
 * 입력: 원문 입력, 구조화된 조건, 적용 상태.
 * 출력: LLM이 추출한 조건 전체와 추천 요청에 실제로 전달된 값.
 *
 * Agent(/api/chat)가 해석과 추천을 한 번에 끝내므로 중간에 사용자가 진행을
 * 승인하는 단계가 없다 — 카드는 "무엇으로 추천됐는지" 확인용으로만 남는다.
 * 호출 시점: ChatPage가 condition_debug 메시지를 렌더링할 때 호출된다.
 * TODO: 조건 직접 수정이 필요해지면 이 컴포넌트 안에 편집 form을 추가한다.
 */

import type { InterpretedConditions, UserConditions } from "../../types";

/*
 * LLM이 추출하는 조건 전체를 표시 순서대로 나열한다. 구형 4필드(location_query 등)만
 * 보여주면 weather_intent/environment처럼 발화의 핵심이 화면에 드러나지 않는다.
 */
const CONDITION_LABELS: [keyof UserConditions, string][] = [
  ["current_location", "현재 위치"],
  ["search_center", "검색 중심"],
  ["place_types", "장소 종류"],
  ["place_tags", "장소 태그"],
  ["weather", "날씨"],
  ["weather_intent", "날씨 의도"],
  ["concentration_intent", "혼잡도 의도"],
  ["transport", "이동 수단"],
  ["max_travel_time", "최대 이동 시간(분)"],
  ["time_available", "가용 시간(분)"],
  ["environment", "실내외"],
  ["companion", "동행"],
  ["budget", "예산"],
  ["exclude_tags", "제외 태그"],
  ["special_requirements", "특별 요구사항"],
];

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "없음";
  if (value === null || value === undefined || value === "") return "없음";
  return String(value);
}

interface ConditionDebugMessageProps {
  userInput: string;
  conditions: InterpretedConditions;
  status: "pending" | "confirmed";
}

export function ConditionDebugMessage({
  userInput,
  conditions,
  status,
}: ConditionDebugMessageProps) {
  return (
    <article className="mr-auto flex w-full max-w-xl flex-col gap-3 rounded-md border border-dashed border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">개발용 입력 해석 결과</h2>
        <span className="rounded bg-amber-200 px-2 py-0.5 text-xs text-amber-900 dark:bg-amber-800 dark:text-amber-100">
          {status === "confirmed" ? "적용됨" : "확인 대기"}
        </span>
      </div>

      <dl className="grid gap-2">
        <div>
          <dt className="font-medium">사용자 원문</dt>
          <dd>{userInput}</dd>
        </div>
        {conditions.raw_conditions ? (
          CONDITION_LABELS.map(([key, label]) => (
            <div key={key}>
              <dt className="font-medium">{label}</dt>
              <dd>{formatValue(conditions.raw_conditions?.[key])}</dd>
            </div>
          ))
        ) : (
          <div>
            <dt className="font-medium">추출된 조건</dt>
            <dd>없음 (RECOMMEND 조건이 비어 있음)</dd>
          </div>
        )}
      </dl>

      <dl className="grid gap-2 border-t border-amber-300 pt-3 dark:border-amber-700">
        <div>
          <dt className="font-medium">추천 요청에 실제로 전달되는 값</dt>
          <dd className="text-xs">
            위치 {conditions.location_query || "없음"} / 카테고리{" "}
            {conditions.preferred_categories.join(", ") || "없음"} / 날씨{" "}
            {conditions.weather_condition ?? "없음"} / 반경 {conditions.search_radius_km}km
          </dd>
        </div>
      </dl>

    </article>
  );
}
