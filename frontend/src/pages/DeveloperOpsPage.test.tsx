/*
 * 역할: /dev-ops 운영 패널의 렌더링과 오류 처리를 검증한다.
 * 입력: mocked fetch 응답(/api/dev/api-usage, /api/dev/db-status).
 * 출력: 호출량 표·한도 게이지·fake 경고·DB 요약에 대한 assertion.
 * 호출 시점: vitest 실행 시 호출된다.
 */

import { render, screen, waitFor } from "@testing-library/react";
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

  expect(await screen.findByText("detailIntro2")).toBeInTheDocument();
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
