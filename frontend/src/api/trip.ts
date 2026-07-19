/*
 * 역할: TripBranch 도메인 endpoint별 API 함수를 제공한다.
 * 입력: 사용자 입력 문자열, 해석된 조건, 이미 노출된 place_id 목록.
 * 출력: 백엔드가 반환한 해석 조건 또는 추천 결과 모델.
 * 호출 시점: InputPage와 ConfirmPage에서 사용자 흐름 진행 시 호출된다.
 * TODO: 실제 endpoint가 늘어나면 파일을 도메인별로 나누고 요청 타입을 세분화한다.
 */

import { apiClient } from "./client";
import type { InterpretedConditions, RecommendationsResponse } from "../types";

export function interpretUserInput(user_input: string) {
  return apiClient.post<InterpretedConditions>("/interpret", { user_input });
}

export function getRecommendations(
  conditions: InterpretedConditions & { shown_place_ids: string[] },
) {
  return apiClient.post<RecommendationsResponse>("/recommendations", conditions);
}
