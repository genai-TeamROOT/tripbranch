// GET /api/health 호출 래퍼. 현재 UI에서 직접 쓰이진 않지만, 개발 중 백엔드 연결
// 확인용이나 향후 상태 배너 등에 재사용할 수 있게 client.ts 패턴을 따라 만들어둠.

import { apiClient } from "./client";

export function getHealth(): Promise<{ status: string }> {
  return apiClient.get<{ status: string }>("/health");
}
