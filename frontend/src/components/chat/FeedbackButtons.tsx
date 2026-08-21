/*
 * 역할: 추천/일정 결과 카드에 붙는 좋아요·싫어요 피드백 버튼.
 * 입력: 피드백을 연결할 session_id/run_id, 찾을 수 있으면 이 턴의 질문·답변
 *   원문·intent.
 * 출력: POST /api/feedback 호출, 선택 상태 표시.
 * 호출 시점: RecommendationResultMessage/ScheduleResultMessage가 결과 카드 하단에 렌더링한다.
 * 참고: roadmap #14. 값은 한 번 기록하면 그대로 두는 append-only 저장이라(B-01 경계
 * 원칙과 별개로 rating 자체는 고정 vocabulary), 버튼을 다시 눌러 바꾸면 새 레코드가
 * 하나 더 쌓인다 — 최신 레코드가 사실상 최종 선택으로 취급된다.
 *
 * "별로예요"는 좋아요와 달리 클릭 즉시 전송하지 않는다 — 사유(comment)를 같은
 * 레코드에 함께 담기 위해 먼저 인라인 입력창을 띄우고, "제출"/"건너뛰기" 중
 * 하나를 눌러야 실제 POST가 나간다. append-only라 "먼저 사유 없이 보내고
 * 나중에 사유 있는 레코드를 하나 더 쌓는" 방식도 가능했지만, 그러면 같은
 * run_id에 dislike 레코드가 중복으로 남아 list_dislikes()에서 두 번 집계되는
 * 문제가 생겨 이 방식을 택했다.
 */

import { useState } from "react";
import { sendFeedback } from "../../api/feedback";
import type { RecordFeedbackRequest } from "../../types";

interface FeedbackButtonsProps {
  sessionId: string;
  runId: string;
  /** 이 턴의 질문·답변 원문·intent. 찾을 수 있을 때만 함께 전송한다(선택 사항). */
  userInput?: string;
  assistantMessage?: string;
  intent?: string;
}

type Rating = RecordFeedbackRequest["rating"];

export function FeedbackButtons({
  sessionId,
  runId,
  userInput,
  assistantMessage,
  intent,
}: FeedbackButtonsProps) {
  const [selected, setSelected] = useState<Rating | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCommentBox, setShowCommentBox] = useState(false);
  const [comment, setComment] = useState("");

  // 카드가 재구성 흐름(dead APPEND_RECOMMENDATIONS 등)에서 run_id 없이 만들어졌다면
  // 어느 턴의 피드백인지 연결할 수 없으니 버튼 자체를 숨긴다.
  if (!sessionId || !runId) return null;

  async function submit(rating: Rating, commentText?: string) {
    if (isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await sendFeedback({
        session_id: sessionId,
        run_id: runId,
        rating,
        user_input: userInput,
        assistant_message: assistantMessage,
        intent,
        comment: commentText,
      });
      setSelected(rating);
      setShowCommentBox(false);
    } catch {
      setError("피드백 전송에 실패했어요. 다시 시도해주세요.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={isSubmitting}
          aria-pressed={selected === "like"}
          onClick={() => submit("like")}
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
          disabled={isSubmitting || showCommentBox}
          aria-pressed={selected === "dislike"}
          onClick={() => setShowCommentBox(true)}
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

      {showCommentBox && (
        <div className="flex flex-col gap-2 rounded-md border border-gray-200 p-2 dark:border-gray-700">
          <label htmlFor={`feedback-comment-${runId}`} className="text-xs text-gray-500 dark:text-gray-400">
            (선택) 어떤 점이 별로였나요?
          </label>
          <textarea
            id={`feedback-comment-${runId}`}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            disabled={isSubmitting}
            rows={2}
            className="w-full rounded-md border border-gray-300 px-2 py-1 text-xs dark:border-gray-700 dark:bg-gray-800"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => submit("dislike", comment.trim() || undefined)}
              className="rounded-md bg-gray-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
            >
              제출
            </button>
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => submit("dislike")}
              className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium disabled:opacity-50 dark:border-gray-700"
            >
              건너뛰기
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
