/*
 * 역할: 추천/일정 결과 카드에 붙는 좋아요·싫어요 피드백 버튼.
 * 입력: 피드백을 연결할 session_id/run_id.
 * 출력: POST /api/feedback 호출, 선택 상태 표시.
 * 호출 시점: RecommendationResultMessage/ScheduleResultMessage가 결과 카드 하단에 렌더링한다.
 * 참고: roadmap #14. 값은 한 번 기록하면 그대로 두는 append-only 저장이라(B-01 경계
 * 원칙과 별개로 rating 자체는 고정 vocabulary), 버튼을 다시 눌러 바꾸면 새 레코드가
 * 하나 더 쌓인다 — 최신 레코드가 사실상 최종 선택으로 취급된다.
 *
 * 싫어요는 좋아요와 달리 클릭 즉시 전송하지 않는다 — 아이콘 아래 짧은 이유를
 * 적을 수 있는 입력창을 펼치고, "제출"(코멘트 포함) 또는 "건너뛰기"(코멘트 없이)를
 * 눌러야 실제로 기록된다. 좋아요는 부연 설명이 필요한 경우가 드물어 그대로
 * 클릭 즉시 전송한다.
 */

import { useState } from "react";
import { sendFeedback } from "../../api/feedback";
import type { RecordFeedbackRequest } from "../../types";

interface FeedbackButtonsProps {
  sessionId: string;
  runId: string;
}

type Rating = RecordFeedbackRequest["rating"];

const COMMENT_MAX_LENGTH = 500;

/* 손모양(엄지) 아이콘. dislike는 같은 path를 180도 회전해 재사용한다 — 두 방향의
   손모양이 점대칭이라 별도 path를 유지하지 않아도 된다. */
function ThumbIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M6.633 10.5c.806 0 1.533-.446 2.031-1.08a9.041 9.041 0 0 1 2.861-2.4c.723-.384 1.35-.956 1.653-1.715a4.498 4.498 0 0 0 .322-1.672V3a.75.75 0 0 1 .75-.75A2.25 2.25 0 0 1 16.5 4.5c0 1.152-.26 2.243-.723 3.218-.266.558.107 1.282.725 1.282h3.126c1.026 0 1.945.694 2.054 1.715.045.422.068.85.068 1.285a11.95 11.95 0 0 1-2.649 7.521c-.388.482-.987.729-1.605.729H13.48c-.483 0-.964-.078-1.423-.23l-3.114-1.04a4.501 4.501 0 0 0-1.423-.23H5.904M14.25 9h2.25M5.904 18.75c.083.205.173.405.27.602.197.4-.078.898-.523.898h-.908c-.889 0-1.713-.518-1.972-1.368a12 12 0 0 1-.521-3.507c0-1.553.295-3.036.831-4.398C3.387 10.203 4.167 9.75 5 9.75h1.053c.472 0 .745.556.5.96a8.958 8.958 0 0 0-1.302 4.665c0 1.194.232 2.333.654 3.375Z" />
    </svg>
  );
}

export function FeedbackButtons({ sessionId, runId }: FeedbackButtonsProps) {
  const [selected, setSelected] = useState<Rating | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCommentOpen, setIsCommentOpen] = useState(false);
  const [comment, setComment] = useState("");

  // 카드가 재구성 흐름(dead APPEND_RECOMMENDATIONS 등)에서 run_id 없이 만들어졌다면
  // 어느 턴의 피드백인지 연결할 수 없으니 버튼 자체를 숨긴다.
  if (!sessionId || !runId) return null;

  async function submit(rating: Rating, commentText?: string) {
    if (isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const trimmed = commentText?.trim();
      await sendFeedback({
        session_id: sessionId,
        run_id: runId,
        rating,
        ...(trimmed ? { comment: trimmed } : {}),
      });
      setSelected(rating);
      setIsCommentOpen(false);
    } catch {
      setError("피드백 전송에 실패했어요. 다시 시도해주세요.");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleLikeClick() {
    void submit("like");
  }

  function handleDislikeClick() {
    if (selected !== null || isCommentOpen) return;
    setIsCommentOpen(true);
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={isSubmitting}
          aria-pressed={selected === "like"}
          aria-label="좋아요"
          title="좋아요"
          onClick={handleLikeClick}
          className={`flex h-9 w-9 items-center justify-center rounded-full disabled:opacity-50 ${
            selected === "like"
              ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
              : "text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-gray-800 dark:hover:text-gray-200"
          }`}
        >
          <ThumbIcon className="h-5 w-5" />
        </button>
        <button
          type="button"
          disabled={isSubmitting}
          aria-pressed={selected === "dislike"}
          aria-expanded={isCommentOpen}
          aria-label="별로예요"
          title="별로예요"
          onClick={handleDislikeClick}
          className={`flex h-9 w-9 items-center justify-center rounded-full disabled:opacity-50 ${
            selected === "dislike" || isCommentOpen
              ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
              : "text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-gray-800 dark:hover:text-gray-200"
          }`}
        >
          <ThumbIcon className="h-5 w-5 rotate-180" />
        </button>
      </div>

      {isCommentOpen && (
        <div className="flex w-64 flex-col items-end gap-1.5 rounded-md border border-gray-200 bg-white p-2 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <textarea
            autoFocus
            value={comment}
            onChange={(event) => setComment(event.target.value.slice(0, COMMENT_MAX_LENGTH))}
            disabled={isSubmitting}
            placeholder="어떤 점이 아쉬웠나요? (선택)"
            rows={2}
            className="w-full resize-none rounded border border-gray-200 bg-transparent p-1.5 text-xs text-gray-700 placeholder:text-gray-400 focus:outline-none disabled:opacity-50 dark:border-gray-700 dark:text-gray-200"
          />
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => void submit("dislike")}
              className="rounded px-2 py-1 text-xs text-gray-500 hover:text-gray-800 disabled:opacity-50 dark:text-gray-400 dark:hover:text-gray-100"
            >
              건너뛰기
            </button>
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => void submit("dislike", comment)}
              className="rounded-md bg-gray-900 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
            >
              제출
            </button>
          </div>
        </div>
      )}

      {error && <span className="text-xs text-red-500">{error}</span>}
    </div>
  );
}
