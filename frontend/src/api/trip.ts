/*
 * 역할: TripBranch 도메인 endpoint별 API 함수를 제공한다.
 * 입력: 사용자 입력 문자열, 해석된 조건, 이미 노출된 place_id 목록.
 * 출력: 백엔드가 반환한 해석 조건 또는 추천 결과 모델.
 * 호출 시점: HomePage와 ChatPage에서 사용자 흐름 진행 시 호출된다.
 * TODO: 실제 endpoint가 늘어나면 파일을 도메인별로 나누고 요청 타입을 세분화한다.
 *
 * NOTE: /api/interpret은 이제 LLMOutput(intent + Intent별 조건)을 반환한다(기존
 * InterpretedConditions 계약에서 교체됨). interpretUserInput()은 기존 화면(HomePage/
 * ChatPage/ConditionDebugMessage)이 계속 InterpretedConditions로 동작하도록 RECOMMEND
 * 결과를 옛 형태로 변환해서 돌려준다 — RECOMMEND가 아니거나 조건이 비어 있으면 빈 값으로
 * 대체된다. Intent 분류·조건 추출 자체를 확인하려면 interpretDebug()를 대신 사용한다.
 */

import { apiClient } from "./client";
import type {
  AgentDebugRequest,
  AgentResponse,
  InterpretDebugRequest,
  InterpretedConditions,
  LLMOutput,
  RecommendationsResponse,
  WeatherCondition,
} from "../types";

function mapStatedWeatherToLegacy(weather: string | null | undefined): WeatherCondition | null {
  if (weather === "good") return "good";
  if (weather === "rain" || weather === "snow" || weather === "hot" || weather === "cold") {
    return "bad";
  }
  return null;
}

function toLegacyConditions(output: LLMOutput): InterpretedConditions {
  const conditions = output.recommend?.conditions;
  const categories = conditions?.place_tags.length
    ? conditions.place_tags
    : (conditions?.place_types ?? []);
  return {
    location_query: conditions?.search_center ?? conditions?.current_location ?? "",
    preferred_categories: categories,
    weather_condition: mapStatedWeatherToLegacy(conditions?.weather),
    search_radius_km: 1.0,
  };
}

export async function interpretUserInput(user_input: string) {
  const output = await apiClient.post<LLMOutput>("/interpret", { user_input });
  return toLegacyConditions(output);
}

export function interpretDebug(request: InterpretDebugRequest) {
  return apiClient.post<LLMOutput>("/interpret", request);
}

export function getRecommendations(
  conditions: InterpretedConditions & { shown_place_ids: string[] },
) {
  return apiClient.post<RecommendationsResponse>("/recommendations", conditions);
}

export function runAgentDebug(request: AgentDebugRequest) {
  return apiClient.post<AgentResponse>("/agent-debug", request);
}
