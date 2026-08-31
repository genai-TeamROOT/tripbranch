/*
 * 역할: 프론트엔드 전역에서 공유하는 TripBranch API와 상태 타입을 정의한다.
 * 입력: 런타임 입력 없음. 백엔드 API 계약을 기준으로 한 TypeScript 선언.
 * 출력: 컴포넌트, 상태, API 클라이언트가 사용하는 타입 별칭과 인터페이스.
 * 호출 시점: 빌드/타입체크와 각 모듈의 import 시 사용된다.
 * TODO: OpenAPI 생성이 도입되면 백엔드 스키마에서 자동 생성하도록 전환한다.
 */

export type WeatherCondition = "good" | "neutral" | "bad";

/** 화면 언어. Runtime은 한국어 계약을 유지하고, 영어는 API 경계에서 번역한다. */
export type Language = "ko" | "en";

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
  /**
   * 취향 검색이 찾은 근거 문장 전부(유사도 내림차순). taste가 0이어도 검색
   * 자체가 실패한 것과 근거를 못 찾은 것을 구분할 수 있게 항상 채워진다 —
   * 빈 배열이면 컷을 넘는 근거가 없었다는 뜻이다. 개발자 디버그 화면 전용.
   */
  taste_evidence: TasteEvidenceQuote[];
  /** 리뷰·블로그에서 문서 단위로 집계한 장소별 상위 취향 태그. */
  preference_tags?: PreferenceTagSummary[];
}

export interface PreferenceTagSummary {
  code: string;
  label: string;
  mention_count: number;
}

export interface TasteEvidenceQuote {
  text: string;
  similarity: number;
}

export type TravelOrigin = "search_center" | "user_location";

/**
 * 비차단형 전환 제안(D-071). travel_origin이 판정되지 않았고 사용자 위치와
 * 검색 기준점이 실제로 다를 때만 채워진다. 있을 때만 "OO 기준으로 다시 보기"
 * 버튼을 노출한다.
 */
export interface TravelOriginToggle {
  alternative_origin: TravelOrigin;
  alternative_origin_name: string;
}

export interface RecommendationsResponse {
  recommendations: RecommendationItem[];
  unverified_recommendations: RecommendationItem[];
  travel_origin_toggle?: TravelOriginToggle | null;
  elapsed_ms: number;
}

/** Gemini Audio API가 짧은 사용자 음성을 전사한 결과. */
export interface TranscriptionResponse {
  text: string;
  elapsed_ms: number;
  model: string;
}

/** 올린 사진과 분위기가 닮은 장소 한 곳. */
export interface PhotoSimilarPlace {
  content_id: string;
  title: string;
  /**
   * 코사인 유사도.
   *
   * **순위를 위한 값이지 "얼마나 닮았다"의 눈금이 아니다.** 사진끼리의 경계값을
   * 아직 재지 않아 컷 없이 상위 N곳을 그대로 받는다(D-094). 백분율로 보여주지
   * 않는다.
   */
  similarity: number;
  /**
   * 장소 벡터를 만든 사진 수. 1이면 대표 이미지 한 장으로 대체된 곳이라
   * 그 한 장에 좌우된다(D-087).
   */
  photo_count: number;
  address?: string | null;
  image_url?: string | null;
}

export interface PhotoSimilarPlacesResponse {
  places: PhotoSimilarPlace[];
  /** 어디를 중심으로 찾았는지. "내 주변에서 찾았어요"를 보여줄 때 쓴다. */
  center_name: string;
  /** 하드 필터를 통과해 사진 검색에 넘어간 후보 수. 0이면 볼 곳 자체가 없었다는 뜻이다. */
  candidate_count: number;
  /** 후보 상한에 걸려 잘린 수. 0이 아니면 반경을 좁히는 편이 낫다. */
  truncated_count: number;
  elapsed_ms: number;
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
  /**
   * 여러 장 보기용 사진 목록. 순서가 곧 보여줄 순서이고 첫 번째가 대표 사진이다.
   * thumbnail_url을 대체하지 않는다 — 목록이 비어도 대표 이미지는 있는 장소가
   * 대부분이라 둘을 함께 본다.
   */
  photos?: PlacePhotoItem[];
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
  population_current_message?: string | null;
  population_observed_at?: string | null;
  /** 향후 예측 중 가장 붐빌 시간대 요약. 과거 추이는 원본 API 미제공으로 없다. */
  population_peak_forecast_summary?: string | null;
  population_forecasts?: PopulationForecastBar[];
  concentration_forecasts?: ConcentrationForecastBar[];
  realtime_area_name?: string | null;
  realtime_observed_at?: string | null;
  realtime_source_url?: string | null;
  realtime_map_url?: string | null;
  realtime_detail_items?: RealtimeInfoDetailItem[];
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

/** 장소 상세 화면에 여러 장으로 보여줄 사진 한 장. */
export interface PlacePhotoItem {
  url: string;
  /** detailImage2의 원본 파일명. 지금은 대체 텍스트 후보로만 쓴다. */
  image_name: string | null;
}

/** 서울시 실시간 도시데이터를 상세 모달에 표시하는 항목. */
export interface RealtimeInfoDetailItem {
  title: string;
  subtitle: string | null;
  details: Record<string, string>;
  thumbnail_url: string | null;
  external_url: string | null;
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
      /** AgentResponse.message_footnote 그대로. 본문 아래 작고 옅은 글씨로 보여준다. */
      footnote?: string;
    }
  | {
      id: string;
      type: "interpretation_summary";
      text: string;
    }
  | {
      id: string;
      type: "photo_similar_result";
      /**
       * 올린 사진의 축소본(data URL). 무엇에 대한 답인지 이력에서 보이게 한다.
       * 브라우저가 못 여는 형식이면 null이고, 그때도 검색 결과는 그대로 나온다.
       */
      imageUrl: string | null;
      /**
       * 검색이 끝나기 전에는 places가 없다. 사진만 먼저 띄우고 "찾는 중"을
       * 보여주기 위해서다 — 응답이 1~2초라 아무것도 없으면 멈춘 것처럼 보인다.
       */
      status: "loading" | "done";
      /** 어디를 중심으로 찾았는지. "내 주변에서 찾았어요"를 보여준다. */
      centerName: string;
      places: PhotoSimilarPlace[];
      /** 하드 필터를 통과해 검색에 넘어간 후보 수. 0이면 볼 곳 자체가 없었다. */
      candidateCount: number;
      elapsedMs: number;
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
      /* 있을 때만 "OO 기준으로 다시 보기" 버튼을 노출한다(D-071). */
      travel_origin_toggle?: TravelOriginToggle | null;
      /* 추천 요청 클릭부터 응답 수신까지의 클라이언트 실측 시간(ms). */
      elapsed_ms: number;
      /* 백엔드가 보고한 서버 처리 시간(ms). 네트워크·렌더 시간은 포함하지 않는다. */
      server_elapsed_ms: number;
    }
  | {
      id: string;
      type: "schedule_result";
      schedule: ScheduleResult;
      /* 일정 요청 클릭부터 응답 수신까지의 클라이언트 실측 시간(ms).
         recommendation_result의 elapsed_ms와 같은 역할이다. */
      elapsed_ms: number;
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
  /*
   * 인텐트와 무관하게 턴 하나가 완결된 답변을 냈을 때(되묻기·에러 제외) 그 턴의
   * 모든 메시지(텍스트+카드) 뒤에 한 번만 붙는 좋아요/싫어요 컨트롤. 결과별
   * 컴포넌트마다 따로 붙이지 않고 여기서 한 곳에 모아 모든 인텐트를 덮는다.
   */
  | {
      id: string;
      type: "feedback";
      sessionId: string;
      runId: string;
      intent?: Intent;
      userInput?: string;
      assistantMessage?: string;
    }
  | {
      id: string;
      type: "clarification";
      text: string;
      options: ClarificationOption[];
    }
  /*
   * 한 턴이 끝난 뒤 다음 발화를 제안하는 버튼 묶음. feedback과 마찬가지로 턴의
   * 맨 뒤에 한 번만 붙고, 사용자가 다음 발화를 보내는 순간 사라진다 — 대화를
   * 위로 거슬러 올라갔을 때 옛 턴의 버튼이 남아 있으면 어느 답변에 대한
   * 제안인지 알 수 없다.
   */
  | {
      id: string;
      type: "follow_up_suggestions";
      suggestions: string[];
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
  language?: Language;
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
   * "OO 기준으로 다시 보기" 비차단형 전환 버튼 클릭(D-071). user_input에는 버튼
   * label을 채워 보내되(채팅 이력 표시용) 라우팅은 이 필드만으로 결정된다 —
   * clarification_choice와 같은 이유로 classify_intent()를 다시 태우지 않는다.
   */
  travel_origin_override?: TravelOrigin | null;
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

/**
 * POST /api/feedback 요청. backend/app/state/service.py의 RecordFeedbackRequest와 대응.
 * user_input/assistant_message는 피드백을 남긴 턴의 질문·답변 원문을 찾을 수 있을
 * 때만 채운다. reason_code는 집계용 표준 싫어요 사유, comment는 선택적 자유 입력이다.
 */
export type FeedbackReasonCode =
  | "intent_mismatch"
  | "clarification_unhelpful"
  | "context_not_preserved"
  | "location_misunderstood"
  | "conditions_not_applied"
  | "recommendation_not_suitable"
  | "other";

export interface RecordFeedbackRequest {
  session_id: string;
  run_id: string;
  rating: "like" | "dislike";
  /** 품질 분석용 사용자 발화 원문 및 최종 응답. */
  user_input?: string;
  assistant_message?: string;
  /** 이 피드백이 달린 턴의 Intent. */
  intent?: string;
  /** 싫어요의 개선용 표준 사유. 좋아요에는 보내지 않는다. */
  reason_code?: FeedbackReasonCode;
  /** 어떤 싫어요 사유에든 선택적으로 남기는 자유 입력(최대 500자). */
  comment?: string;
}

/** POST /api/feedback 응답. */
export interface RecordFeedbackResponse {
  recorded_at: string;
}

/** GET /api/feedback/stats의 intent 항목 1개. (TP-146) */
export interface FeedbackIntentCount {
  intent: string;
  count: number;
}

/**
 * GET /api/feedback/stats 응답. backend/app/state/service.py의
 * FeedbackStatsResponse와 대응.
 *
 * reason_code_counts는 표준 7개 사유 + "unclassified"(사유 없이 남긴
 * dislike) 키를 항상 전부 포함한다. like 행은 여기 안 들어간다.
 * top_intents는 상위 N개(요청한 top_intents 개수)만 담고, 그 뒤 롱테일은
 * other_intent_count로 합쳐진다. intent 자체가 없는 행은 missing_intent_count.
 */
export interface FeedbackStatsResponse {
  since: string | null;
  until: string | null;
  total: number;
  rating_counts: Record<"like" | "dislike", number>;
  reason_code_counts: Record<FeedbackReasonCode | "unclassified", number>;
  top_intents: FeedbackIntentCount[];
  other_intent_count: number;
  missing_intent_count: number;
}

export interface TraceStepStat {
  step: string;
  count: number;
  avg_latency_ms: number | null;
  max_latency_ms: number | null;
  error_count: number;
}

export interface TraceRecentError {
  session_id: string;
  run_id: string;
  step: string;
  error_type: string;
  recorded_at: string;
}

/**
 * GET /api/trace/stats 응답. backend/app/state/service.py의
 * TraceStatsResponse와 대응.
 *
 * step_stats는 reason_code_counts와 달리 고정된 값 집합이 아니다 —
 * 등장한 step만 담긴다(step은 A/C/D가 자유롭게 붙이는 문자열이라
 * B가 미리 알 수 없다). recent_errors는 error_type이 있는 행만
 * 최근순으로 상위 N건(요청한 recent_errors_limit개).
 */
export interface TraceStatsResponse {
  since: string | null;
  until: string | null;
  total: number;
  step_stats: TraceStepStat[];
  recent_errors: TraceRecentError[];
}

export interface AgentResponse {
  llm_output: LLMOutput;
  state: StateApplyResponse;
  recommendations: RecommendationsResponse | null;
  schedule?: ScheduleResult | null;
  comparison?: ComparisonResult | null;
  info_place_card?: InfoPlaceCard | null;
  message: string;
  /** message에 넣기엔 긴 부가 정보(D-085). 있으면 본문 아래 작고 옅은 글씨로 보여준다. */
  message_footnote?: string | null;
  /**
   * 이 턴 뒤에 버튼으로 보여줄 다음 발화 후보(0~3개). 누르면 이 문구가 그대로
   * user_input으로 재전송된다 — 되묻기 버튼(ClarificationOption)이 id로 Intent를
   * 못 박는 것과 다르다.
   */
  suggested_follow_ups?: string[];
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
  /** 카드 바로 위에 즉시 표시할 고정 안내문. */
  message?: string;
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
  | { type: "follow_ups"; data: AgentStreamFollowUpsEvent }
  | { type: "error"; data: AgentStreamErrorEvent };

/*
 * done **뒤에** 오는 유일한 이벤트다. 후속 질문 생성은 답변이 이미 화면에 다 뜬 뒤에
 * 도는 호출이라, done보다 앞에 두면 그 시간만큼 턴이 안 끝나 답변과 카드 아래에
 * 로딩 말풍선이 한 번 더 뜬 것처럼 보인다(D-102). 제안할 게 없으면 서버가 이 이벤트를
 * 아예 보내지 않는다.
 */
export interface AgentStreamFollowUpsEvent {
  suggestions: string[];
  elapsed_ms: number;
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

export interface CandidateConcentrationDebug {
  place_id: string;
  name: string;
  status: string;
  is_proxy: boolean;
  /** 값을 빌려온 실제 장소와 후보로부터의 거리. is_proxy=false면 둘 다 null. */
  proxy_place_name: string | null;
  proxy_distance_km: number | null;
}

/*
 * 이번 턴에 쓰인 위치 하나. name은 지오코딩 결과가 아니라 사용자가 말한 원문이다
 * (백엔드 LocationDebug 주석 참고 — resolved_name은 도로명 주소라 표시용이 아니다).
 * source가 "device_gps"면 부를 이름이 없어 name이 null이다.
 */
export interface LocationDebug {
  name: string | null;
  /**
   * "search_center"는 사용자 위치를 몰라 검색 위치를 시작점으로 대체했다는 뜻이다.
   * "travel_origin_override"는 사용자 위치를 알면서도 발화가 조사로 출발점을
   * 확정해("안국역에서 10분", D-071) 검색 위치를 고른 것이다 — 대체가 아니라
   * 정상 동작이라 둘을 구분한다.
   */
  source: "query" | "device_gps" | "search_center" | "travel_origin_override";
  latitude: number;
  longitude: number;
}

export interface ToolExecutionDebug {
  operation?: "context_fetch" | "info_concentration" | "info_realtime_commercial" | "info_realtime_population" | "info_realtime_citydata" | "candidate_enrichment" | "compare_fetch";
  request_id: string;
  status: string;
  latency_ms: number | null;
  providers: ToolProviderDebug[];
  context_items: ToolContextItemDebug[];
  rule_versions: Record<string, string>;
  resolved_location_name: string | null;
  resolved_location_address: string | null;
  /*
   * 위치 세 갈래. RECOMMEND(context_fetch)에서만 채워진다 — INFO/COMPARE는 C의 위치
   * 해석을 거치지 않고 A가 기기 GPS로 직접 경로를 조회한다. 이전 실행 이력에는
   * 없을 수 있어 optional로 둔다.
   */
  search_location?: LocationDebug | null;
  user_location?: LocationDebug | null;
  route_origin?: LocationDebug | null;
  error_code: string | null;
  clarification_code: string | null;
  is_proxy: boolean | null;
  /**
   * info_realtime_population 전용. 우리 121곳 목록엔 없지만 서울시 API는 실제로
   * 지원하는 지역을 찾았을 때만 채워진다(TP-141/D-084). 응답 판정에는 영향을
   * 주지 않는 감시용 신호 — 이전 실행 이력에는 없을 수 있어 optional로 둔다.
   */
  stale_area_detected?: {
    probed_area_name: string;
    probed_area_code: string | null;
    matched_area_name: string;
    matched_area_distance_km: number;
  } | null;
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
  /**
   * 같은 모델에 대해 타임아웃·429·5xx로 다시 시도한 횟수(0=첫 시도에서 끝남).
   * 재시도가 성공하면 로그도 안 남고 attempted_models도 안 늘어나, 이 값이
   * 없으면 latency_ms가 큰 이유가 "모델이 느렸다"인지 "재시도했다"인지 구분이
   * 안 된다. 스트리밍 호출은 항상 0. 이전 실행 이력에는 없을 수 있다.
   */
  retry_count?: number | null;
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
