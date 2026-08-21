/*
 * 역할: 프론트엔드 전역에서 공유하는 TripBranch API와 상태 타입을 정의한다.
 * 입력: 런타임 입력 없음. 백엔드 API 계약을 기준으로 한 TypeScript 선언.
 * 출력: 컴포넌트, 상태, API 클라이언트가 사용하는 타입 별칭과 인터페이스.
 * 호출 시점: 빌드/타입체크와 각 모듈의 import 시 사용된다.
 * TODO: OpenAPI 생성이 도입되면 백엔드 스키마에서 자동 생성하도록 전환한다.
 */

export type WeatherCondition = "good" | "neutral" | "bad";

export type EnvironmentType = "indoor" | "outdoor" | "mixed" | "unknown";

/** 실측 경로를 조회한 이동수단. 지금 서버가 실제로 내려보내는 값은 "walking"뿐이다. */
export type TravelMode = "walking" | "transit" | "driving";

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
  /** D가 현재 적용한 당일 운영 구간으로 만든 표기값. 예: "09:00~18:00" */
  operating_hours_display?: string | null;
  /*
   * 실측 경로로 잰 이동 거리·시간과 그 이동수단. 세 값은 함께 채워지거나 함께
   * null이다. null이면 실측이 없다는 뜻이므로 distance_km(직선거리)로만 말한다 —
   * 프론트가 직선거리에 임의 속도를 곱해 시간을 만들면 근거 문장과 다른 값이
   * 표시된다(TP-102에서 41분 vs 24분으로 드러났다).
   */
  travel_distance_m?: number | null;
  travel_duration_seconds?: number | null;
  travel_mode?: TravelMode | null;
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

/** Gemini Audio API가 짧은 사용자 음성을 전사한 결과. */
export interface TranscriptionResponse {
  text: string;
  elapsed_ms: number;
  model: string;
}

export interface ScheduleItem {
  order: number;
  place_id: string;
  place_name: string;
  estimated_arrival: string;
  estimated_duration_min: number;
  travel_to_next_min: number | null;
  reason: string;
  // 백엔드가 항상 채워 보내지만(app.schemas.ScheduleItem, 기본값 []), 기존
  // 테스트 픽스처가 이 필드 없이 만든 객체와도 호환되도록 optional로 둔다.
  // estimated_arrival이 후보 운영시간과 어긋날 때 planner.py가 결정적으로
  // 채우는 경고 — LLM이 생성하지 않는다.
  warnings?: string[];
}

export interface ScheduleResult {
  items: ScheduleItem[];
  total_duration_min: number;
  route_summary: string;
  basis_note: string;
  /* 백엔드가 보고한 일정 편성 파이프라인 처리 시간(ms). RecommendationResult의
     server_elapsed_ms와 같은 역할이다(SCHEDULE-10 후속). */
  elapsed_ms: number;
}

export interface ComparisonItem {
  place_id: string;
  place_name: string;
  rank: number;
  distance_km: number | null;
  remaining_minutes: number | null;
  environment_type: string | null;
  /** TRAVEL_TIME 전용(TP-105/106 실측 연결). 좌표는 실측 조회에만 쓰이고 화면에는 없다. */
  latitude: number | null;
  longitude: number | null;
  travel_distance_km: number | null;
  travel_walking_minutes: number | null;
  travel_driving_minutes: number | null;
  travel_transit_minutes: number | null;
}

export interface ComparisonResult {
  criteria: "time" | "travel_time" | "overall";
  items: ComparisonItem[];
}

/** INFO 장소 질의에 함께 내려오는 펼침형 상세 카드 데이터. */
export interface InfoPlaceCard {
  question_type: string;
  /** 사용자가 물어본 항목의 실제 답. 카드 전체 정보와 섞지 않는다. */
  answer_fields: Record<string, string>;
  place_id: string | null;
  place_name: string | null;
  /** 목적지 좌표. 지도 앱 길찾기 딥링크용. 좌표를 못 얻은 카드는 null. */
  latitude: number | null;
  longitude: number | null;
  thumbnail_url: string | null;
  overview: string | null;
  operating_hours: string | null;
  rest_date: string | null;
  parking: string | null;
  parking_fee: string | null;
  fee: string | null;
  baby_carriage: string | null;
  pet: string | null;
  credit_card: string | null;
  restroom: string | null;
  homepage: string | null;
  population_current_level?: string | null;
  population_observed_at?: string | null;
  population_forecasts?: PopulationForecastBar[];
  concentration_forecasts?: ConcentrationForecastBar[];
}

export interface PopulationForecastBar {
  forecast_at: string;
  congestion_level: string | null;
  population_min: number | null;
  population_max: number | null;
}

export interface ConcentrationForecastBar {
  forecast_date: string;
  concentration_rate: number;
  concentration_level: string;
  concentration_label: string;
}

/** 추천 카드 클릭 시 C PlaceDetails를 직접 조회하는 응답이다. */
export interface RecommendationPlaceDetailResponse {
  status: "success" | "no_data" | "unavailable";
  requested_place_id: string | null;
  place_card: InfoPlaceCard | null;
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
      /** SSE로 요약 문장을 받는 중인 말풍선이다. */
      streaming?: boolean;
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
      /* 좋아요/싫어요 피드백을 이 턴(run)에 연결하기 위한 식별자. */
      sessionId: string;
      runId: string;
    }
  | {
      id: string;
      type: "schedule_result";
      schedule: ScheduleResult;
      /* 일정 요청 클릭부터 응답 수신까지의 클라이언트 실측 시간(ms).
         recommendation_result의 elapsed_ms와 같은 역할이다. */
      elapsed_ms: number;
      /* 좋아요/싫어요 피드백을 이 턴(run)에 연결하기 위한 식별자. */
      sessionId: string;
      runId: string;
    }
  | {
      id: string;
      type: "place_info_result";
      card: InfoPlaceCard;
    }
  | {
      id: string;
      type: "compare_result";
      comparison: ComparisonResult;
    }
  | {
      id: string;
      type: "clarification";
      text: string;
      options: ClarificationOption[];
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

/** 되묻기에 붙는 버튼 하나. 클릭 시 id를 그대로 clarification_choice로 돌려보낸다. */
export interface ClarificationOption {
  id: string;
  label: string;
  resolved_intent: Intent;
}

export interface ClarificationPayload {
  missing_fields: { field: string; reason: string }[];
  ambiguous_fields: { field: string; user_input: string; candidates: string[]; reason: string }[];
  message: string;
  options: ClarificationOption[];
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
  /** 직전 INFO 상세 카드의 장소명. "여기/이곳" 같은 대화 지시어 해소 후보다. */
  conversation_place_name?: string | null;
  /*
   * 되묻기 버튼 클릭 시 ClarificationOption.id를 그대로 echo. user_input에는 버튼
   * label을 채워 보내되(채팅 이력 표시용) 라우팅은 이 필드만으로 결정된다.
   */
  clarification_choice?: string | null;
  /*
   * 개발자용 채팅(/dev-chat) 전용 디버그 스위치. true면 이번 턴은 폐점 후보도
   * 항상 채점에 포함한다 — no_data_closed 되묻기를 매번 누르지 않고 강제로
   * 켤 수 있다.
   */
  debug_ignore_operating_hours?: boolean;
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

/** POST /api/feedback 요청. backend/app/state/service.py의 RecordFeedbackRequest와 대응. */
export interface RecordFeedbackRequest {
  session_id: string;
  run_id: string;
  rating: "like" | "dislike";
}

/** POST /api/feedback 응답. */
export interface RecordFeedbackResponse {
  recorded_at: string;
}

export interface AgentResponse {
  llm_output: LLMOutput;
  state: StateApplyResponse;
  recommendations: RecommendationsResponse | null;
  schedule?: ScheduleResult | null;
  comparison?: ComparisonResult | null;
  info_place_card?: InfoPlaceCard | null;
  message: string;
  llm_execution?: LLMExecutionMetadata | null;
  tool_execution?: ToolExecutionDebug | null;
  tool_executions?: ToolExecutionDebug[];
}

export type AgentProgressStage =
  | "interpreting"
  | "merging_conditions"
  | "fetching_context"
  | "scoring"
  | "scheduling"
  | "composing_message";

export interface AgentProgressEvent {
  stage: AgentProgressStage;
  message: string;
  elapsed_ms: number;
}

/** SSE 서버 경과 시간을 바탕으로 계산한 Agent 단계별 실행 구간. */
export interface AgentStageTiming {
  stage: AgentProgressStage;
  message: string;
  started_at_ms: number;
  duration_ms: number;
  /** 답변 스트림의 message_start부터 첫 message_delta까지 걸린 시간(TTFT). */
  time_to_first_token_ms?: number;
}

export interface AgentStreamResultEvent {
  elapsed_ms: number;
  llm_output: LLMOutput;
  state: StateApplyResponse;
  recommendations: RecommendationsResponse;
}

export interface AgentStreamMessageDeltaEvent {
  elapsed_ms: number;
  text: string;
}

/** 카드 없이 LLM 본문을 먼저 표시할 때 로딩 말풍선을 연다. */
export interface AgentStreamMessageStartEvent {
  elapsed_ms: number;
  intent: Intent;
}

export interface AgentStreamDoneEvent {
  elapsed_ms: number;
  response: AgentResponse;
}

export interface AgentStreamErrorEvent extends ApiErrorBody {
  elapsed_ms: number;
}

export type AgentStreamEvent =
  | { type: "progress"; data: AgentProgressEvent }
  | { type: "result"; data: AgentStreamResultEvent }
  | { type: "message_start"; data: AgentStreamMessageStartEvent }
  | { type: "message_delta"; data: AgentStreamMessageDeltaEvent }
  | { type: "done"; data: AgentStreamDoneEvent }
  | { type: "error"; data: AgentStreamErrorEvent };

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

export interface CandidateConcentrationDebug {
  place_id: string;
  name: string;
  status: string;
  is_proxy: boolean;
  /** 값을 빌려온 실제 장소와 후보로부터의 거리. is_proxy=false면 둘 다 null. */
  proxy_place_name: string | null;
  proxy_distance_km: number | null;
}

export interface ToolExecutionDebug {
  operation?: "context_fetch" | "info_concentration" | "info_realtime_commercial" | "info_realtime_citydata" | "candidate_enrichment" | "compare_fetch";
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
  is_proxy: boolean | null;
  candidate_status_counts: Record<string, number>;
  /** candidate_enrichment 전용: 후보별로 혼잡도가 어디서 온 값인지. */
  candidate_concentration?: CandidateConcentrationDebug[];
}

export interface LLMCallMetadata {
  operation: string;
  attempted_models: string[];
  served_model: string | null;
  /** 구조화 LLM 호출 전체 경과 시간(ms). 이전 실행 이력에는 없을 수 있다. */
  latency_ms?: number | null;
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
  stageTimings: AgentStageTiming[];
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
