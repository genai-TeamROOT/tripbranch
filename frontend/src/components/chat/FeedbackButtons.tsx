/*
 * 역할: 추천/일정 결과 카드에 붙는 좋아요·싫어요 피드백 버튼.
 * 입력: 피드백을 연결할 session_id/run_id.
 * 출력: POST /api/feedback 호출, 선택 상태 표시.
 * 호출 시점: RecommendationResultMessage/ScheduleResultMessage가 결과 카드 하단에 렌더링한다.
 * 참고: roadmap #14. 값은 한 번 기록하면 그대로 두는 append-only 저장이라(B-01 경계
 * 원칙과 별개로 rating 자체는 고정 vocabulary), 버튼을 다시 눌러 바꾸면 새 레코드가
 * 하나 더 쌓인다 — 최신 레코드가 사실상 최종 선택으로 취급된다.
 */

import { useState } from "react";
import { sendFeedback } from "../../api/feedback";
import type { RecordFeedbackRequest } from "../../types";

interface FeedbackButtonsProps {
  sessionId: string;
  runId: string;
}

type Rating = RecordFeedbackRequest["rating"];

export function FeedbackButtons({ sessionId, runId }: FeedbackButtonsProps) {
  const [selected, setSelected] = useState<Rating | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 카드가 재구성 흐름(dead APPEND_RECOMMENDATIONS 등)에서 run_id 없이 만들어졌다면
  // 어느 턴의 피드백인지 연결할 수 없으니 버튼 자체를 숨긴다.
  if (!sessionId || !runId) return null;

  async function handleClick(rating: Rating) {
    if (isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await sendFeedback({ session_id: sessionId, run_id: runId, rating });
      setSelected(rating);
    } catch {
      setError("피드백 전송에 실패했어요. 다시 시도해주세요.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        disabled={isSubmitting}
        aria-pressed={selected === "like"}
        onClick={() => handleClick("like")}
        className={`rounded-md border px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${
          selected === "like"
            ? "border-gray-900 bg-gray-900 text-white dark:border-gray-100 dark:bg-gray-100 dark:text-gray-900"
            : "border-gray-300 text-gray-600 dark:border-gray-700 dark:text-gray-300"
        }`}
      >
        좋아요
      </button>
      <button
        type="button"
        disabled={isSubmitting}
        aria-pressed={selected === "dislike"}
        onClick={() => handleClick("dislike")}
        className={`rounded-md border px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${
          selected === "dislike"
            ? "border-gray-900 bg-gray-900 text-white dark:border-gray-100 dark:bg-gray-100 dark:text-gray-900"
            : "border-gray-300 text-gray-600 dark:border-gray-700 dark:text-gray-300"
        }`}
      >
        별로예요
      </button>
      {error && <span className="text-xs text-red-500">{error}</span>}
    </div>
  );
}
