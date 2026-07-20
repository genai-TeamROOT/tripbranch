/*
 * 역할: 개발 모드에서 사용자 입력 해석 결과를 채팅 메시지로 표시한다.
 * 입력: 원문 입력, 구조화된 조건, 확인 상태, 추천 진행 콜백.
 * 출력: 개발용 조건 카드와 추천 진행 버튼.
 * 호출 시점: ChatPage가 condition_debug 메시지를 렌더링할 때 호출된다.
 * TODO: 조건 직접 수정이 필요해지면 이 컴포넌트 안에 편집 form을 추가한다.
 */

import type { InterpretedConditions } from "../../types";

interface ConditionDebugMessageProps {
  userInput: string;
  conditions: InterpretedConditions;
  status: "pending" | "confirmed";
  isLoading: boolean;
  onConfirm: () => void;
}

export function ConditionDebugMessage({
  userInput,
  conditions,
  status,
  isLoading,
  onConfirm,
}: ConditionDebugMessageProps) {
  return (
    <article className="mr-auto flex w-full max-w-xl flex-col gap-3 rounded-md border border-dashed border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">개발용 입력 해석 결과</h2>
        <span className="rounded bg-amber-200 px-2 py-0.5 text-xs text-amber-900 dark:bg-amber-800 dark:text-amber-100">
          {status === "confirmed" ? "확인됨" : "확인 대기"}
        </span>
      </div>

      <dl className="grid gap-2">
        <div>
          <dt className="font-medium">사용자 원문</dt>
          <dd>{userInput}</dd>
        </div>
        <div>
          <dt className="font-medium">구조화된 위치</dt>
          <dd>{conditions.location_query}</dd>
        </div>
        <div>
          <dt className="font-medium">선호 카테고리</dt>
          <dd>{conditions.preferred_categories.join(", ") || "없음"}</dd>
        </div>
        <div>
          <dt className="font-medium">상황 또는 날씨 조건</dt>
          <dd>{conditions.weather_condition ?? "없음"}</dd>
        </div>
        <div>
          <dt className="font-medium">이동 가능 범위</dt>
          <dd>{conditions.search_radius_km}km</dd>
        </div>
      </dl>

      <button
        type="button"
        disabled={isLoading || status === "confirmed"}
        onClick={onConfirm}
        className="w-fit rounded-md bg-amber-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-amber-200 dark:text-amber-950"
      >
        {isLoading ? "추천 요청 중..." : status === "confirmed" ? "추천 요청 완료" : "추천 진행"}
      </button>
    </article>
  );
}
