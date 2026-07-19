// POST /api/interpret 호출 래퍼. InputPage에서 사용자의 자유 입력을 서버로 보내
// InterpretedConditions를 받아온다. 타입은 types/domain.ts를 그대로 사용.

import { apiClient } from "./client";
import type { InterpretedConditions } from "../types/domain";

export function interpretUserInput(userInput: string): Promise<InterpretedConditions> {
  return apiClient.post<InterpretedConditions>("/interpret", { user_input: userInput });
}
