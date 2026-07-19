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
