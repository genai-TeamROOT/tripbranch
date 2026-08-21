/*
 * 역할: 응답 피드백(좋아요/싫어요) API 함수.
 * 입력: session_id, run_id, rating.
 * 출력: 백엔드가 반환한 기록 시각.
 * 호출 시점: RecommendationResultMessage/ScheduleResultMessage의 피드백 버튼 클릭 시.
 * 참고: backend/app/routes/feedback.py POST /api/feedback.
 */

import { apiClient } from "./client";
import type { RecordFeedbackRequest, RecordFeedbackResponse } from "../types";

export function sendFeedback(request: RecordFeedbackRequest) {
  return apiClient.post<RecordFeedbackResponse>("/feedback", request);
}
