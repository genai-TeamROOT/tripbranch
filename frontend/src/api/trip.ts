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
