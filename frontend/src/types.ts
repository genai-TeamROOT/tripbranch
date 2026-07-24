/*
 * 역할: 프론트엔드 전역에서 공유하는 TripBranch API와 상태 타입을 정의한다.
 * 입력: 런타임 입력 없음. 백엔드 API 계약을 기준으로 한 TypeScript 선언.
 * 출력: 컴포넌트, 상태, API 클라이언트가 사용하는 타입 별칭과 인터페이스.
 * 호출 시점: 빌드/타입체크와 각 모듈의 import 시 사용된다.
 * TODO: OpenAPI 생성이 도입되면 백엔드 스키마에서 자동 생성하도록 전환한다.
 */

export type WeatherCondition = "good" | "neutral" | "bad";

export type EnvironmentType = "indoor" | "outdoor" | "mixed" | "unknown";

export interface InterpretedConditions {
  location_query: string;
  preferred_categories: string[];
  weather_condition: WeatherCondition | null;
  search_radius_km: number;
}

export interface RecommendationItem {
  place_id: string;
  name: string;
  category: string;
  distance_km: number;
  remaining_minutes: number | null;
  environment_type: EnvironmentType;
  recommendation_reason: string;
  warnings: string[];
  score: number;
  feature_scores: Record<string, number | null>;
  weights_used: Record<string, number>;
}

export interface RecommendationsResponse {
  recommendations: RecommendationItem[];
  unverified_recommendations: RecommendationItem[];
  elapsed_ms: number;
}

export type ChatPhase =
  | "idle"
  | "interpreting"
  | "waiting_for_debug_confirmation"
  | "recommending"
  | "ready"
  | "error";

export type ChatMessage =
  | {
      id: string;
      type: "user_text";
      text: string;
    }
  | {
      id: string;
      type: "assistant_text";
      text: string;
    }
  | {
      id: string;
      type: "interpretation_summary";
      text: string;
    }
  | {
      id: string;
      type: "condition_debug";
      userInput: string;
      conditions: InterpretedConditions;
      status: "pending" | "confirmed";
    }
  | {
      id: string;
      type: "recommendation_result";
      recommendations: RecommendationItem[];
      unverified_recommendations: RecommendationItem[];
    };

export interface ApiErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  details: unknown;
}

// --- LLMOutput(Intent 분류 + 조건 추출) 관련 타입 ---
// backend/app/schemas.py의 LLMOutput 계약을 그대로 옮긴 개발용 디버그 타입.
// 화면 표시에 필요한 최소한만 좁혀서 선언하며, enum 값은 string으로 느슨하게 받는다.

export type Intent = "RECOMMEND" | "INFO" | "MODIFY" | "COMPARE" | "GENERAL" | "OUT_OF_SCOPE";

export type LLMOutputStatus = "complete" | "needs_clarification";

export interface UserConditions {
  current_location: string | null;
  search_center: string | null;
  place_types: string[];
  place_tags: string[];
  weather: string | null;
  weather_intent: string | null;
  transport: string | null;
  max_travel_time: number | null;
  time_available: number | null;
  environment: string | null;
  companion: string | null;
  budget: string | null;
  exclude_tags: string[];
  special_requirements: string[];
}

export interface RecommendPayload {
  conditions: UserConditions;
}

export interface InfoPayload {
  place_name: string | null;
  place_context: string;
  question_type: string;
  specific_question: string | null;
}

export interface ModifyPayload {
  modify_type: "REJECT_ALL" | "CHANGE_CONDITION";
  condition_changes: UserConditions | null;
  changed_fields: string[];
}

export interface ComparePayload {
  targets: "all" | number[];
  criteria: string;
}

export interface GeneralPayload {
  topic: string;
  original_question: string;
}

export interface OutOfScopePayload {
  category: string;
  severity: string;
}

export interface ClarificationPayload {
  missing_fields: { field: string; reason: string }[];
  ambiguous_fields: { field: string; user_input: string; candidates: string[]; reason: string }[];
  message: string;
}

export interface LLMOutput {
  intent: Intent;
  status: LLMOutputStatus;
  recommend: RecommendPayload | null;
  info: InfoPayload | null;
  modify: ModifyPayload | null;
  compare: ComparePayload | null;
  general: GeneralPayload | null;
  out_of_scope: OutOfScopePayload | null;
  clarification: ClarificationPayload | null;
}

export interface InterpretDebugRequest {
  user_input: string;
  has_previous_recommendation?: boolean;
  shown_place_count?: number;
  current_conditions?: Partial<UserConditions> | null;
}
