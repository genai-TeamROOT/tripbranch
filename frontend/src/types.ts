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
  /*
   * 개발용 표시 전용. 위 4개 필드는 구형 계약이라 LLM이 추출한 14개 조건 중
   * 일부만 담을 수 있어(weather_intent/environment 등이 유실된다), 원본을 그대로
   * 실어 ConditionDebugMessage가 전부 보여줄 수 있게 한다.
   * /api/recommendations 요청에는 보내지 않는다(trip.ts에서 제거).
   * TODO: /api/chat 전환으로 LLMOutput을 직접 쓰게 되면 이 필드는 삭제한다.
   */
  raw_conditions?: UserConditions | null;
}

export interface RecommendationItem {
  place_id: string;
  name: string;
  category: string;
  distance_km: number;
  remaining_minutes: number | null;
  environment_type: EnvironmentType;
  recommendation_reason: string;
  explanations: string[];
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
      intent?: Intent;
      status?: LLMOutputStatus;
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
      /*
       * B가 병합한 누적 조건. 실제 추천에 쓰이는 값이며, 되묻기 턴에서는 이번 턴
       * 추출분(conditions.raw_conditions)과 달라진다 — 앞 턴 조건이 살아 있기 때문.
      */
      mergedConditions: UserConditions | null;
      /* 해당 사용자 발화에 대해 Agent가 최종 분류한 Intent. */
      intent?: Intent;
      status: "pending" | "confirmed";
    }
  /*
   * 로컬 테스트용 "/status" 명령의 결과. 서버 호출 없이 화면에만 쌓이며,
   * 조회에 실패하면 error에 사유가 담긴다.
   */
  | {
      id: string;
      type: "session_status";
      status: SessionContextResponse | null;
      error: string | null;
    }
  | {
      id: string;
      type: "recommendation_result";
      recommendations: RecommendationItem[];
      unverified_recommendations: RecommendationItem[];
      /* 추천 요청 클릭부터 응답 수신까지의 클라이언트 실측 시간(ms). */
      elapsed_ms: number;
      /* 백엔드가 보고한 서버 처리 시간(ms). 네트워크·렌더 시간은 포함하지 않는다. */
      server_elapsed_ms: number;
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

export type Intent =
  | "RECOMMEND"
  | "INFO"
  | "MODIFY"
  | "COMPARE"
  | "GENERAL"
  | "OUT_OF_SCOPE"
  | "SCHEDULE";

export type LLMOutputStatus = "complete" | "needs_clarification";

export interface UserConditions {
  current_location: string | null;
  search_center: string | null;
  place_types: string[];
  place_tags: string[];
  weather: string | null;
  weather_intent: string | null;
  concentration_intent?: string | null;
  transport: string | null;
  max_travel_time: number | null;
  time_available: number | null;
  environment: string | null;
  companion: string | null;
  budget: string | null;
  exclude_tags: string[];
  special_requirements: string[];
  /*
   * 백엔드 UserConditions에는 아직 없는 필드다. Agent가 반경을 산출해 내려주게 되면
   * toLegacyConditions()가 이 값을 우선 사용하고, 없으면 기본값(2.0km)을 쓴다.
   */
  search_radius_km?: number | null;
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

/*
 * /api/interpret 응답은 LLMOutput 자체가 아니라 세션 상태와 함께 감싼 형태다
 * (backend InterpretResponse). state는 현재 화면에서 쓰지 않아 좁게 선언한다.
 */
export interface InterpretResponse {
  output: LLMOutput;
  state: unknown;
}

export interface InterpretDebugRequest {
  user_input: string;
  has_previous_recommendation?: boolean;
  shown_place_count?: number;
  current_conditions?: Partial<UserConditions> | null;
}

// --- Agent Runtime(run_agent()) 디버그 관련 타입 ---
// backend/app/schemas.py의 AgentRequest/AgentResponse 계약을 그대로 옮긴 개발용 타입.

export interface AgentDebugRequest {
  user_input: string;
  session_id?: string | null;
  device_location?: string | null;
}

export interface SessionState {
  session_id: string;
  run_id: string;
  session_created: boolean;
  condition_version: number;
  condition_changed: boolean;
  user_conditions: UserConditions;
  shown_place_ids: string[];
  excluded_place_ids: string[];
  gps_expired: boolean;
  weather_expired: boolean;
}

export interface StateApplyResponse {
  session_id: string;
  run_id: string;
  session_created: boolean;
  user_conditions: UserConditions;
  api_context?: ApiContextView;
  condition_version: number;
  condition_changed: boolean;
  applied_operations?: StateOperation[];
  ignored_operations?: IgnoredStateOperation[];
  excluded_place_ids: string[];
  reset_applied: string | null;
}

export interface StateOperation {
  op: string;
  field: string | null;
  before_value?: unknown;
  after_value?: unknown;
  value?: unknown;
}

export interface IgnoredStateOperation {
  operation: StateOperation;
  reason: string;
}

/* GET /api/state/{session_id} 응답(계약 6.3절). 로컬 "/status" 표시에 쓴다. */
export interface ApiContextView {
  gps_location: string | null;
  api_weather: string | null;
  gps_expired: boolean;
  weather_expired: boolean;
}

export interface SessionContextResponse {
  session_id: string | null;
  session_exists: boolean;
  has_recommendation: boolean;
  recommended_count: number;
  shown_place_ids: string[];
  excluded_place_ids: string[];
  last_recommended_run_id: string | null;
  last_intent: string | null;
  pending_clarification: string | null;
  user_conditions: UserConditions;
  api_context: ApiContextView;
  condition_version: number;
}

export interface AgentResponse {
  llm_output: LLMOutput;
  state: StateApplyResponse;
  recommendations: RecommendationsResponse | null;
  message: string;
  llm_execution?: LLMExecutionMetadata | null;
  tool_execution?: ToolExecutionDebug | null;
}

export interface ToolProviderDebug {
  source: string;
  status: string;
  retrieved_at: string | null;
}

/** fetched=false는 C가 그 항목을 조회하지 않았다는 뜻 — 조회 후 실패와 구분된다. */
export interface ToolContextItemDebug {
  key: string;
  fetched: boolean;
  status: string | null;
  error_code: string | null;
  warning_codes: string[];
  item_count: number | null;
}

export interface ToolExecutionDebug {
  request_id: string;
  status: string;
  latency_ms: number | null;
  providers: ToolProviderDebug[];
  context_items: ToolContextItemDebug[];
  rule_versions: Record<string, string>;
  resolved_location_name: string | null;
  resolved_location_address: string | null;
  error_code: string | null;
  clarification_code: string | null;
}

export interface LLMCallMetadata {
  operation: string;
  attempted_models: string[];
  served_model: string | null;
}

export interface LLMExecutionMetadata {
  calls: LLMCallMetadata[];
}

export interface DeveloperAuditFailure {
  code: string;
  message: string;
  retryable: boolean;
  details: unknown;
}

export interface DeveloperAuditTurn {
  id: string;
  userInput: string;
  intent: Intent | "ERROR";
  status: LLMOutputStatus | "error";
  message: string;
  sessionId: string | null;
  runId: string | null;
  deviceLocation: string | null;
  elapsedMsClient: number;
  serverElapsedMs: number | null;
  extractedConditions: InterpretedConditions | null;
  beforeConditions: UserConditions | null;
  afterConditions: UserConditions | null;
  recommendations: RecommendationsResponse | null;
  response: AgentResponse | null;
  failure: DeveloperAuditFailure | null;
}

/*
 * POST /api/chat 요청·응답. 현재 백엔드가 AgentRequest/AgentResponse를 그대로
 * 사용하므로 별칭으로 둔다.
 * TODO: 공개 계약이 좁혀지면(D-016) 이 타입을 독립 선언으로 바꾼다.
 */
export type ChatRequest = AgentDebugRequest;
export type ChatResponse = AgentResponse;
