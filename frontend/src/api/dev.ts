/*
 * 역할: 개발자 Ops 패널(/dev-ops)이 쓰는 /api/dev/* 엔드포인트 클라이언트.
 * 입력: 조회 파라미터(지역 코드 등).
 * 출력: 외부 API 호출량 집계와 장소 DB 상태 스냅샷.
 * 호출 시점: /dev-ops 화면이 열리거나 폴링할 때 호출된다.
 *
 * 이 엔드포인트는 백엔드가 APP_ENV=local일 때만 등록된다. 배포 환경에서는
 * 404가 돌아오므로 화면에서 "로컬 전용"임을 안내한다.
 */

import { apiClient } from "./client";

export type ApiUsageEntry = {
  provider: string;
  operation: string;
  count: number;
  ok: number;
  error: number;
  today_count: number;
  today_ok: number;
  today_error: number;
  daily_limit: number | null;
  avg_latency_ms: number | null;
  max_latency_ms: number | null;
  last_called_at: string | null;
  last_status: string | null;
};

export type ApiUsageSnapshot = {
  process_started_at: string;
  generated_at: string;
  today: string;
  timezone: string;
  provider_modes: Record<string, string>;
  totals: { count: number; ok: number; error: number };
  today_totals: { count: number; ok: number; error: number };
  entries: ApiUsageEntry[];
};

export type PlaceTableSummary = {
  area_code: string;
  district_code: string;
  total: number;
  active: number;
  inactive: number;
  detail_fetch_status: Record<string, number>;
  operating_parse_status: Record<string, number>;
  operating_parser_version: Record<string, number>;
  latest_detail_fetched_at: string | null;
};

export type SyncRunRow = {
  id?: string;
  area_code?: string;
  district_code?: string;
  status?: string;
  started_at?: string;
  completed_at?: string | null;
  api_total_count?: number | null;
  processed_count?: number;
  success_count?: number;
  failed_count?: number;
  new_count?: number;
  updated_count?: number;
  deactivated_count?: number;
  error_summary?: Record<string, number> | null;
};

export type SyncLockRow = {
  area_code?: string;
  district_code?: string;
  sync_run_id?: string;
  acquired_at?: string;
  expires_at?: string;
};

export type DbStatus = {
  area_code: string;
  district_code: string;
  places: PlaceTableSummary;
  place_enrichments_count: number;
  place_concentration_mappings_count: number;
  sync_runs: SyncRunRow[];
  sync_locks: SyncLockRow[];
  detail_ttl_days: number;
};

export function fetchApiUsage() {
  return apiClient.get<ApiUsageSnapshot>("/dev/api-usage");
}

export function resetApiUsage() {
  return apiClient.post<ApiUsageSnapshot>("/dev/api-usage/reset", {});
}

export function fetchDbStatus(areaCode?: string, districtCode?: string) {
  const params = new URLSearchParams();
  if (areaCode) params.set("area_code", areaCode);
  if (districtCode) params.set("district_code", districtCode);
  const query = params.toString();
  return apiClient.get<DbStatus>(`/dev/db-status${query ? `?${query}` : ""}`);
}
