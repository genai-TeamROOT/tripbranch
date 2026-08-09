/*
 * 역할: /dev-ops 운영 패널의 렌더링과 오류 처리를 검증한다.
 * 입력: mocked fetch 응답(/api/dev/api-usage, /api/dev/db-status).
 * 출력: 호출량 표·한도 게이지·fake 경고·DB 요약에 대한 assertion.
 * 호출 시점: vitest 실행 시 호출된다.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { DeveloperOpsPage } from "./DeveloperOpsPage";

const usageSnapshot = {
  process_started_at: "2026-08-09T09:00:00+09:00",
  generated_at: "2026-08-09T09:10:00+09:00",
  today: "2026-08-09",
  timezone: "Asia/Seoul",
  provider_modes: {
    llm: "real",
    place: "real",
    geocoding: "real",
    local_search: "real",
    weather: "real",
    concentration: "real",
    holiday: "real",
  },
  totals: { count: 517, ok: 515, error: 2 },
  today_totals: { count: 517, ok: 515, error: 2 },
  entries: [
    {
      provider: "tour_api",
      operation: "detailIntro2",
      count: 512,
      ok: 510,
      error: 2,
      today_count: 512,
      today_ok: 510,
      today_error: 2,
      daily_limit: 1000,
      avg_latency_ms: 220.5,
      max_latency_ms: 1800,
      last_called_at: "2026-08-09T09:09:00+09:00",
      last_status: "200",
    },
  ],
};

const dbStatus = {
  area_code: "11",
  district_code: "110",
  places: {
    area_code: "11",
    district_code: "110",
    total: 844,
    active: 843,
    inactive: 1,
    detail_fetch_status: { succeeded: 840, failed: 4 },
    operating_parse_status: { parsed: 700, unknown: 144 },
    operating_parser_version: { "operating-hours-1.0.0": 844 },
    latest_detail_fetched_at: "2026-08-08T14:00:00+09:00",
  },
  place_enrichments_count: 51,
  place_concentration_mappings_count: 101,
  sync_runs: [
    {
      id: "run-1",
      area_code: "11",
      district_code: "110",
      status: "success",
      started_at: "2026-08-08T13:00:00+09:00",
      completed_at: "2026-08-08T14:00:00+09:00",
      processed_count: 844,
      new_count: 1,
      updated_count: 16,
      deactivated_count: 1,
      failed_count: 0,
      error_summary: null,
    },
  ],
  sync_locks: [],
  detail_ttl_days: 30,
};

function mockFetch(handler: (url: string) => { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const { status, body } = handler(String(input));
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/dev-ops"]}>
      <DeveloperOpsPage />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

it("호출량 표와 일일 한도 게이지를 보여준다", async () => {
  mockFetch((url) => ({
    status: 200,
    body: url.includes("api-usage") ? usageSnapshot : dbStatus,
  }));

  renderPage();

  // detailIntro2는 호출량 표와 DB 갱신 패널의 한도 경고 문구 양쪽에 나온다.
  expect((await screen.findAllByText("detailIntro2")).length).toBeGreaterThan(0);
  expect(screen.getByText("512 / 1000")).toBeInTheDocument();
  // 누적 호출과 오늘 호출 두 카드에 같은 값이 뜬다.
  expect(screen.getAllByText("517")).toHaveLength(2);
});

it("fake provider가 있으면 표가 비는 이유를 경고로 알린다", async () => {
  mockFetch((url) => ({
    status: 200,
    body: url.includes("api-usage")
      ? {
          ...usageSnapshot,
          provider_modes: { ...usageSnapshot.provider_modes, place: "fake" },
          totals: { count: 0, ok: 0, error: 0 },
          today_totals: { count: 0, ok: 0, error: 0 },
          entries: [],
        }
      : dbStatus,
  }));

  renderPage();

  // 빈 표를 "트래픽 없음"으로 오독하면 fake로 뜬 서버를 real로 착각한다(D-042).
  expect(await screen.findByText(/Fake Provider: 장소/)).toBeInTheDocument();
  expect(screen.getByText("아직 기록된 외부 호출이 없습니다.")).toBeInTheDocument();
});

it("DB 상태 요약과 동기화 이력을 보여준다", async () => {
  mockFetch((url) => ({
    status: 200,
    body: url.includes("api-usage") ? usageSnapshot : dbStatus,
  }));

  renderPage();

  expect(await screen.findByText("843")).toBeInTheDocument();
  expect(screen.getByText("전체 844 · 비활성 1")).toBeInTheDocument();
  expect(screen.getByText("success")).toBeInTheDocument();
  // 어떤 테이블에 반영됐는지는 place_sync_runs 행에 없어 카운트에서 파생한다.
  expect(screen.getByText("places")).toBeInTheDocument();
  expect(screen.getByText("신규 1 · 갱신 16 · 비활성 1")).toBeInTheDocument();
  expect(screen.getByText("place_sync_locks")).toBeInTheDocument();
  expect(screen.getByText("잠금 없음 — 실행 가능한 상태예요.")).toBeInTheDocument();
});

it("라우터가 없는 서버(404)에는 APP_ENV 확인을 안내한다", async () => {
  mockFetch(() => ({
    status: 404,
    body: {
      error: {
        code: "invalid_request",
        message: "요청한 API를 찾을 수 없어요.",
        retryable: false,
        details: null,
      },
    },
  }));

  renderPage();

  await waitFor(() => {
    expect(screen.getAllByText(/APP_ENV=local/).length).toBeGreaterThan(0);
  });
});

const reconcileResult = {
  area_code: "11",
  district_code: "110",
  snapshot: "places_api_snapshot_20260809.csv",
  snapshot_count: 844,
  baseline: "places_api_snapshot_20260808.csv",
  baseline_count: 844,
  reconciliation: "places_reconciliation_20260809.csv",
  skipped_columns: [],
  counts: { added: 1, removed: 1, updated: 2 },
  detail_content_ids: ["3", "4"],
  detail_excluded_ids: ["1"],
  rows: [
    {
      content_id: "4",
      title: "새 장소",
      content_type_id: "12",
      change_type: "added" as const,
      changed_columns: [],
      previous: {},
      current: {},
    },
    {
      content_id: "1",
      title: "좌표만 바뀐 장소",
      content_type_id: "12",
      change_type: "updated" as const,
      changed_columns: ["latitude", "longitude"],
      previous: {},
      current: {},
    },
  ],
};

const runningJob = {
  job_id: "job-1",
  params: {
    area_code: "11",
    district_code: "110",
    snapshot: "places_api_snapshot_20260809.csv",
    dry_run: true,
    detail_target_count: 2,
    added_count: 1,
  },
  status: "running",
  started_at: "2026-08-09T19:00:00+09:00",
  finished_at: null,
  phase: "details",
  processed: 1,
  total: 2,
  result: null,
  error: null,
  unmapped_new_place_ids: [],
};

function mockSyncFetch() {
  const posted: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") {
        posted.push({ url, body: JSON.parse(String(init.body)) });
      }
      const body = url.includes("api-usage")
        ? usageSnapshot
        : url.includes("reconcile")
          ? reconcileResult
          : url.includes("place-sync/apply") || url.includes("place-sync/jobs")
            ? runningJob
            : dbStatus;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return posted;
}

it("대조 결과와 상세조회 대상 건수를 보여준다", async () => {
  mockSyncFetch();
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole("button", { name: "1. 스냅샷 대조" }));

  expect(await screen.findByText("새 장소")).toBeInTheDocument();
  expect(screen.getByText("예상 외부 호출: 목록 0회 + 상세조회 2회")).toBeInTheDocument();
  // 수정시각이 안 바뀐 건은 상세조회에서 빠지되 조용히 사라지지 않아야 한다.
  expect(screen.getByText(/상세조회 제외 1건/)).toBeInTheDocument();
});

it("확인 문자열을 정확히 입력해야 반영이 시작된다", async () => {
  const posted = mockSyncFetch();
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole("button", { name: "1. 스냅샷 대조" }));
  await user.click(await screen.findByRole("button", { name: "2. 반영 실행" }));

  const execute = screen.getByRole("button", { name: "실행" });
  expect(execute).toBeDisabled();

  await user.type(screen.getByRole("textbox"), "11-999");
  expect(execute).toBeDisabled();

  await user.clear(screen.getByRole("textbox"));
  await user.type(screen.getByRole("textbox"), "11-110");
  await user.click(execute);

  const applyCall = posted.find((call) => call.url.includes("place-sync/apply"));
  expect(applyCall?.body).toEqual({
    snapshot: "places_api_snapshot_20260809.csv",
    detail_content_ids: ["3", "4"],
    // 신규 장소는 반영 후 집중률 매핑 유무를 확인하는 데 쓰인다.
    added_content_ids: ["4"],
    dry_run: true,
    confirm: "11-110",
  });
});

it("제외된 건을 포함하도록 체크하면 상세조회 대상에 들어간다", async () => {
  const posted = mockSyncFetch();
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole("button", { name: "1. 스냅샷 대조" }));
  await user.click(await screen.findByRole("checkbox", { name: /상세조회 제외 1건/ }));
  expect(
    screen.getByText("예상 외부 호출: 목록 0회 + 상세조회 3회"),
  ).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "2. 반영 실행" }));
  await user.type(screen.getByRole("textbox"), "11-110");
  await user.click(screen.getByRole("button", { name: "실행" }));

  const applyCall = posted.find((call) => call.url.includes("place-sync/apply"));
  expect(applyCall?.body).toMatchObject({ detail_content_ids: ["3", "4", "1"] });
});
