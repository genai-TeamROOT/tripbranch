// POST /api/recommendations 호출 래퍼. ConfirmPage(최초 추천)와 ResultsPage
// (다른 장소 보기/반경 넓히기)에서 공통으로 사용한다. shown_place_ids를 함께 보내
// 이미 본 장소를 서버가 제외하도록 한다.

import { apiClient } from "./client";
import type { InterpretedConditions, RecommendationsResponse } from "../types/domain";

export interface RecommendationRequestPayload extends InterpretedConditions {
  shown_place_ids: string[];
}

export function getRecommendations(
  payload: RecommendationRequestPayload,
): Promise<RecommendationsResponse> {
  return apiClient.post<RecommendationsResponse>("/recommendations", payload);
}
