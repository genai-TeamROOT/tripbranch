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
  ChatRequest,
  ChatResponse,
  InterpretDebugRequest,
  InterpretResponse,
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

/*
 * Agent가 반경을 주지 않을 때 쓰는 기본값. 백엔드
 * place_search_policy.DEFAULT_PLACE_SEARCH_RADIUS_KM(2.0)과 맞춘다.
 */
const DEFAULT_SEARCH_RADIUS_KM = 2.0;

/*
 * LLMOutput의 RECOMMEND 조건을 화면 표시용 InterpretedConditions로 옮긴다.
 * /api/chat 전환 이후에는 추천 요청 본문이 아니라 조건 카드 표시에만 쓰인다.
 */
export function toDisplayConditions(output: LLMOutput): InterpretedConditions | null {
  return output.recommend ? toLegacyConditions(output) : null;
}

function toLegacyConditions(output: LLMOutput): InterpretedConditions {
  const conditions = output.recommend?.conditions;
  const categories = conditions?.place_tags.length
    ? conditions.place_tags
    : (conditions?.place_types ?? []);
  return {
    // 사용자가 위치를 말하지 않았으면 비워 둔다. 임의의 지명을 채우면 말한 적 없는
    // 장소를 조건 카드와 안내 문구에 그대로 보여주게 된다.
    location_query: conditions?.search_center ?? conditions?.current_location ?? "",
    preferred_categories: categories,
    weather_condition: mapStatedWeatherToLegacy(conditions?.weather),
    // 현재 UserConditions에는 반경 필드가 없어 항상 기본값이 쓰인다. Agent가 반경을
    // 제공하게 되면 여기서 그 값을 우선 사용한다.
    search_radius_km: conditions?.search_radius_km ?? DEFAULT_SEARCH_RADIUS_KM,
    // 구형 4필드로 축소되면서 버려지는 나머지 조건을 개발용 표시를 위해 보존한다.
    raw_conditions: conditions ?? null,
  };
}

export async function interpretUserInput(user_input: string) {
  const response = await apiClient.post<InterpretResponse>("/interpret", { user_input });
  return toLegacyConditions(response.output);
}

export async function interpretDebug(request: InterpretDebugRequest) {
  const response = await apiClient.post<InterpretResponse>("/interpret", request);
  return response.output;
}

export function getRecommendations(
  conditions: InterpretedConditions & { shown_place_ids: string[] },
) {
  // raw_conditions는 개발용 표시 전용이라 요청 본문에서 제외한다.
  const payload = { ...conditions };
  delete payload.raw_conditions;
  return apiClient.post<RecommendationsResponse>("/recommendations", payload);
}

export function runAgentDebug(request: AgentDebugRequest) {
  return apiClient.post<AgentResponse>("/agent-debug", request);
}

/*
 * 실사용 흐름(HomePage/ChatPage)의 단일 진입점. Intent 분류 → 조건 병합 → Tool →
 * Scoring → 챗봇 메시지까지 한 번의 호출로 끝난다.
 * agent-debug와 응답 형태는 같지만 라우트가 다르다 — 개발용 패널과 실사용 경로를
 * 섞지 않기 위함이다.
 */
export function sendChat(request: ChatRequest) {
  return apiClient.post<ChatResponse>("/chat", request);
}
