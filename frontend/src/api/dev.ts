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

/** 장소 행 묶음 하나의 요약. 구 하나일 수도, 전 구 합계일 수도 있다. */
export type PlaceSummary = {
  total: number;
  active: number;
  inactive: number;
  detail_fetch_status: Record<string, number>;
  operating_parse_status: Record<string, number>;
  operating_parser_version: Record<string, number>;
  latest_detail_fetched_at: string | null;
};

/** 구 하나의 요약. district_name은 코드 자료에 없는 구면 null이라 코드로 표시한다. */
export type DistrictPlaceSummary = PlaceSummary & {
  area_code: string;
  district_code: string;
  district_name: string | null;
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
  /** 적재된 전 구 합계. 탭의 "전체"가 읽는다. */
  overall: PlaceSummary;
  /** 적재된 구만 들어온다 — 이 배열이 곧 화면의 탭 목록이다. */
  districts: DistrictPlaceSummary[];
  /* 아래 네 값은 구로 나누지 않는다. 두 카운트는 테이블에 구 열이 없고(둘 다
   * content_id 기준), 이력과 잠금은 전 구를 한 목록으로 보는 편이 "어느 구를
   * 언제 돌렸나"를 읽기 쉽다. */
  place_enrichments_count: number;
  place_concentration_mappings_count: number;
  sync_runs: SyncRunRow[];
  sync_locks: SyncLockRow[];
  detail_ttl_days: number;
  /* 오늘 detailIntro2를 몇 번 불렀는지. place_sync_runs에서 세므로 서버를
   * 재시작해도 남고 scripts 실행분도 잡히지만, 여전히 하한이다 — 재시도는 안
   * 세지고 중간에 죽은 실행은 값이 비어 있다(runs_without_count). */
  detail_calls_today: {
    count: number;
    runs: number;
    runs_without_count: number;
    daily_limit: number | null;
  };
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

/** 무엇을 기준으로 대조했는지.
 *
 * `database`는 스냅샷 파일이 없어 places에서 기준을 만든 경우다. 그 기준은 파일로
 * 남지 않는다 — 파일명 날짜가 오늘과 겹치면 이번 대조가 쓰는 파일에 덮어써진다.
 * `unavailable`은 "DB에 없다"가 아니라 "자격증명이 없어 확인하지 못했다"다. */
export type BaselineSource = "file" | "database" | "none" | "unavailable";

export type ReconcileResult = {
  area_code: string;
  district_code: string;
  snapshot: string;
  snapshot_count: number;
  baseline: string | null;
  baseline_source: BaselineSource;
  baseline_count?: number;
  reconciliation?: string;
  skipped_columns: string[];
  counts: { added: number; removed: number; updated: number };
  detail_content_ids: string[];
  detail_excluded_ids: string[];
  /* 이번 변경분은 아니지만 반영이 **함께** 부르는 장소. 지난 실행에서 상세를 못
   * 채운(pending·failed) 건이다. 빼고 계산하면 화면이 "15회"라고 해놓고 실제로는
   * 157회를 쓴다. */
  detail_backfill_ids: string[];
  /** DB를 실제로 확인했는지. false면 위 목록이 0건이라는 뜻이 아니라 못 봤다는 뜻이다. */
  detail_backfill_checked: boolean;
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
    /** 상한이 걸린 실행은 비활성화를 건너뛴다 — 목록을 다 처리하지 못했으므로. */
    details_limit: number | null;
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

/** 화면이 고를 수 있는 구. 자료가 있는 구만 들어온다. */
export type SyncDistrict = {
  area_code: string;
  district_code: string;
  district_name: string | null;
  place_count: number;
  active_count: number;
  latest_snapshot: string | null;
};

/** 코드 입력을 검증할 시군구 사전 항목. */
export type KnownDistrict = {
  area_code: string;
  district_code: string;
  district_name: string;
};

export type SyncDistricts = {
  loaded: SyncDistrict[];
  known: KnownDistrict[];
};

export function fetchSyncDistricts() {
  return apiClient.get<SyncDistricts>("/dev/place-sync/districts");
}

export function reconcilePlaces(input: {
  areaCode: string;
  districtCode: string;
  baseline?: string;
}) {
  return apiClient.post<ReconcileResult>("/dev/place-sync/reconcile", {
    area_code: input.areaCode,
    district_code: input.districtCode,
    baseline: input.baseline ?? null,
  });
}

/*
 * 구를 반드시 싣는다. 빠뜨리면 서버가 설정 기본값(종로구)으로 실행해, 다른 구
 * 스냅샷을 반영했을 때 종로구 활성 장소가 전부 비활성화된다. 서버도 스냅샷
 * 내용과 구가 다르면 거부하지만, 그 거부에 걸리지 않으려면 여기서 맞게 보내야
 * 한다.
 */
export function applyPlaceSync(input: {
  areaCode: string;
  districtCode: string;
  snapshot: string;
  detailContentIds: string[];
  addedContentIds: string[];
  dryRun: boolean;
  detailsLimit: number | null;
  confirm: string;
}) {
  return apiClient.post<SyncJob>("/dev/place-sync/apply", {
    area_code: input.areaCode,
    district_code: input.districtCode,
    snapshot: input.snapshot,
    detail_content_ids: input.detailContentIds,
    added_content_ids: input.addedContentIds,
    dry_run: input.dryRun,
    details_limit: input.detailsLimit,
    confirm: input.confirm,
  });
}

export function fetchSyncJob(jobId: string) {
  return apiClient.get<SyncJob>(`/dev/place-sync/jobs/${jobId}`);
}

/*
 * 구를 인자로 받지 않는다 — 어떤 구가 적재돼 있는지는 places가 아는 사실이라
 * 응답이 구 목록까지 함께 준다. 탭 전환은 이미 받아둔 값을 고르는 것이라
 * 추가 요청이 없다.
 */
export function fetchDbStatus() {
  return apiClient.get<DbStatus>("/dev/db-status");
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
