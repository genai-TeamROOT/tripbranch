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

export type ApiExchange = {
  id: string;
  started_at: string;
  provider: string;
  operation: string;
  method: string;
  /** 쿼리스트링이 제거된 URL. 원문 URL에는 serviceKey가 들어간다. */
  url: string;
  query: Record<string, string>;
  request_headers: Record<string, string>;
  request_body: string | null;
  request_body_truncated: boolean;
  status: string;
  ok: boolean;
  latency_ms: number;
  response_headers: Record<string, string>;
  response_body: string | null;
  response_body_truncated: boolean;
  response_bytes: number;
  error: string | null;
};

export type ApiExchangeSnapshot = {
  enabled: boolean;
  capacity: number;
  max_body_bytes: number;
  items: ApiExchange[];
};

export function fetchExchanges() {
  return apiClient.get<ApiExchangeSnapshot>("/dev/exchanges");
}

export function setExchangeCapture(enabled: boolean) {
  return apiClient.post<ApiExchangeSnapshot>("/dev/exchanges/capture", { enabled });
}

export function clearExchanges() {
  return apiClient.post<ApiExchangeSnapshot>("/dev/exchanges/clear", {});
}

export function fetchApiUsage() {
  return apiClient.get<ApiUsageSnapshot>("/dev/api-usage");
}

export function resetApiUsage() {
  return apiClient.post<ApiUsageSnapshot>("/dev/api-usage/reset", {});
}

export type ReconcileRow = {
  content_id: string;
  title: string;
  content_type_id: string;
  change_type: "added" | "removed" | "updated";
  changed_columns: string[];
  previous: Record<string, string>;
  current: Record<string, string>;
};

export type ReconcileResult = {
  area_code: string;
  district_code: string;
  snapshot: string;
  snapshot_count: number;
  baseline: string | null;
  baseline_count?: number;
  reconciliation?: string;
  skipped_columns: string[];
  counts: { added: number; removed: number; updated: number };
  detail_content_ids: string[];
  detail_excluded_ids: string[];
  rows: ReconcileRow[];
  message?: string;
};

export type SyncJob = {
  job_id: string;
  params: {
    area_code: string;
    district_code: string;
    snapshot: string;
    dry_run: boolean;
    detail_target_count: number;
    added_count: number;
  };
  status: string;
  started_at: string;
  finished_at: string | null;
  phase: string;
  processed: number;
  total: number;
  result: {
    status: string;
    dry_run: boolean;
    sync_run_id: string | null;
    processed_count: number;
    success_count: number;
    failed_count: number;
    new_count: number;
    updated_count: number;
    deactivated_count: number;
    detail_target_count: number;
    detail_attempted_count: number;
    reparse_count: number;
    error_summary: Record<string, number>;
  } | null;
  error: string | null;
  /** 새로 들어왔는데 집중률 매핑이 없는 장소. 매핑이 없으면 혼잡도 조회가 생략된다. */
  unmapped_new_place_ids: string[];
};

export function reconcilePlaces(baseline?: string) {
  return apiClient.post<ReconcileResult>("/dev/place-sync/reconcile", {
    baseline: baseline ?? null,
  });
}

export function applyPlaceSync(input: {
  snapshot: string;
  detailContentIds: string[];
  addedContentIds: string[];
  dryRun: boolean;
  confirm: string;
}) {
  return apiClient.post<SyncJob>("/dev/place-sync/apply", {
    snapshot: input.snapshot,
    detail_content_ids: input.detailContentIds,
    added_content_ids: input.addedContentIds,
    dry_run: input.dryRun,
    confirm: input.confirm,
  });
}

export function fetchSyncJob(jobId: string) {
  return apiClient.get<SyncJob>(`/dev/place-sync/jobs/${jobId}`);
}

export function fetchDbStatus(areaCode?: string, districtCode?: string) {
  const params = new URLSearchParams();
  if (areaCode) params.set("area_code", areaCode);
  if (districtCode) params.set("district_code", districtCode);
  const query = params.toString();
  return apiClient.get<DbStatus>(`/dev/db-status${query ? `?${query}` : ""}`);
}

export type NearestArea = {
  area_code: string | null;
  area_name: string | null;
  distance_km: number | null;
};

/*
 * 기기 GPS 좌표에 붙일 근사 지역 이름을 얻는다. 서울시 상권 82개 지역의 대표 좌표는
 * 백엔드에만 있고, 프론트로 복사하면 표가 두 곳으로 갈라진다.
 *
 * 같은 좌표를 여러 턴이 공유하므로(GPS는 턴마다 바뀌지 않는다) 좌표 문자열을 키로
 * 캐싱한다. 조회 실패는 throw하지 않고 빈 결과로 낮춘다 — 이름을 못 붙이는 것이
 * 감사 패널 전체를 막을 이유는 아니다.
 */
const EMPTY_NEAREST_AREA: NearestArea = {
  area_code: null,
  area_name: null,
  distance_km: null,
};
const nearestAreaCache = new Map<string, Promise<NearestArea>>();

export function fetchNearestArea(location: string): Promise<NearestArea> {
  const cached = nearestAreaCache.get(location);
  if (cached) return cached;

  const pending = apiClient
    .get<NearestArea>(`/dev/nearest-area?location=${encodeURIComponent(location)}`)
    .catch(() => EMPTY_NEAREST_AREA);
  nearestAreaCache.set(location, pending);
  return pending;
}
