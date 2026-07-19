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
