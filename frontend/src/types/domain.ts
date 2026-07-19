// 프론트에서 쓰는 기본 타입. 백엔드 Pydantic 스키마와 필드명을 snake_case로 동일하게
// 맞춰서 손으로 관리한다 - 지금 단계의 기본 진실 소스는 이 파일이다.
//
// ../generated/api-types.ts (OpenAPI 자동 생성 타입)도 `npm run generate:api-types`로
// 언제든 만들 수 있지만, 아직 프론트 코드 어디서도 가져다 쓰지 않는다. API 스키마가
// 안정화되면 이 수동 타입들을 generated 타입 기반 alias로 점진적으로 바꾸는 걸 다음
// 단계로 남겨둔다(README "OpenAPI 타입 생성" 참고). 지금은 팀 개발을 시작하는 데
// 필수 절차가 아니다.

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
  total_score: number;
  score_breakdown: Record<string, number>;
}

export interface RecommendationsResponse {
  recommendations: RecommendationItem[];
  unverified_recommendations: RecommendationItem[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  details: unknown;
}
