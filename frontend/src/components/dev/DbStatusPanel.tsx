/*
 * 역할: 장소 DB(places / place_enrichments / place_sync_runs)의 현재 상태를 보여준다.
 * 입력: /api/dev/db-status 응답.
 * 출력: 테이블 건수 요약, 상태 분포, 최근 동기화 이력, 잠금 상태.
 * 호출 시점: DeveloperOpsPage가 렌더링될 때, 그리고 새로고침 시.
 *
 * 조회 전용이다. 동기화 실행(대조·반영)은 별도 패널이 담당한다.
 */

import type { DbStatus, SyncLockRow, SyncRunRow } from "../../api/dev";

const RUN_STATUS_TONES: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100",
  partial_failure: "bg-amber-100 text-amber-900 dark:bg-amber-950/50 dark:text-amber-100",
  failed: "bg-red-100 text-red-900 dark:bg-red-950/50 dark:text-red-100",
  running: "bg-blue-100 text-blue-900 dark:bg-blue-950/50 dark:text-blue-100",
};

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ko-KR", { hour12: false });
}

function Distribution({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return <span className="text-xs text-gray-400">없음</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([key, value]) => (
        <span
          key={key}
          className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] dark:bg-gray-800"
        >
          {key} {value}
        </span>
      ))}
    </div>
  );
}

/** 이 실행이 실제로 쓴 테이블. place_sync_runs 행에는 이 정보가 없어 카운트에서 파생한다.
 *
 * 동기화가 건드리는 테이블은 세 개뿐이다(리포지토리 쓰기 경로 전수 확인).
 * place_enrichments와 place_concentration_mappings는 별도 스크립트 소관이라
 * 여기 절대 나타나지 않는 게 정상이다.
 */
function syncedTables(run: SyncRunRow): { table: string; detail: string }[] {
  const tables: { table: string; detail: string }[] = [];
  const processed = run.processed_count ?? 0;
  if (processed > 0) {
    const parts: string[] = [];
    if (run.new_count) parts.push(`신규 ${run.new_count}`);
    if (run.updated_count) parts.push(`갱신 ${run.updated_count}`);
    if (run.deactivated_count) parts.push(`비활성 ${run.deactivated_count}`);
    tables.push({
      table: "places",
      detail: parts.length > 0 ? parts.join(" · ") : `${processed}건 변경 없음`,
    });
  }
  // 상태는 왼쪽 배지에 이미 있으므로 여기서는 되풀이하지 않는다.
  tables.push({ table: "place_sync_runs", detail: "이력 1건" });
  tables.push({
    table: "place_sync_locks",
    detail: run.status === "running" ? "잠금 보유 중" : "획득·해제",
  });
  return tables;
}

function SyncedTables({ run }: { run: SyncRunRow }) {
  return (
    <div className="flex flex-col gap-0.5">
      {syncedTables(run).map(({ table, detail }) => (
        <span key={table} className="whitespace-nowrap">
          <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] dark:bg-gray-800">
            {table}
          </span>
          <span className="ml-1.5 text-[11px] text-gray-500">{detail}</span>
        </span>
      ))}
    </div>
  );
}

function LockRow({ lock }: { lock: SyncLockRow }) {
  const expiresAt = lock.expires_at ? new Date(lock.expires_at) : null;
  // 만료 판정은 저장소가 아니라 화면에서 한다 — 저장소가 걸러버리면 "잠금이 남아
  // 실행이 막힌다"와 "잠금이 없다"가 구분되지 않는다.
  const expired = expiresAt !== null && expiresAt.getTime() <= Date.now();
  return (
    <li className="flex flex-wrap items-center gap-2 py-1 text-xs">
      <span
        className={`rounded px-1.5 py-0.5 font-semibold ${
          expired
            ? "bg-gray-200 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
            : "bg-blue-100 text-blue-900 dark:bg-blue-950/50 dark:text-blue-100"
        }`}
      >
        {expired ? "만료됨" : "잠금 중"}
      </span>
      <span>
        {lock.area_code}-{lock.district_code}
      </span>
      <span className="text-gray-500">
        획득 {formatDateTime(lock.acquired_at)} · 만료 {formatDateTime(lock.expires_at)}
      </span>
      <span className="font-mono text-[11px] text-gray-400">{lock.sync_run_id}</span>
    </li>
  );
}

function SyncRunTable({ runs }: { runs: SyncRunRow[] }) {
  if (runs.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-gray-300 p-4 text-sm text-gray-500 dark:border-gray-700">
        동기화 이력이 없습니다.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-240 text-left text-xs">
        <thead className="text-gray-500 dark:text-gray-400">
          <tr className="border-b border-gray-200 dark:border-gray-800">
            <th className="py-1.5 pr-2 font-medium">상태</th>
            <th className="py-1.5 pr-2 font-medium">지역</th>
            <th className="py-1.5 pr-2 font-medium">반영 테이블</th>
            <th className="py-1.5 pr-2 font-medium">시작</th>
            <th className="py-1.5 pr-2 font-medium">완료</th>
            <th className="py-1.5 pr-2 text-right font-medium">처리</th>
            <th className="py-1.5 pr-2 text-right font-medium">신규</th>
            <th className="py-1.5 pr-2 text-right font-medium">갱신</th>
            <th className="py-1.5 pr-2 text-right font-medium">비활성</th>
            <th className="py-1.5 pr-2 text-right font-medium">실패</th>
            <th className="py-1.5 pr-2 font-medium">오류</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run, index) => (
            <tr
              key={run.id ?? index}
              className="border-b border-gray-100 dark:border-gray-800/60"
            >
              <td className="py-1.5 pr-2">
                <span
                  className={`rounded px-1.5 py-0.5 font-semibold ${
                    RUN_STATUS_TONES[run.status ?? ""] ?? "bg-gray-100 dark:bg-gray-800"
                  }`}
                >
                  {run.status ?? "-"}
                </span>
              </td>
              <td className="py-1.5 pr-2">
                {run.area_code}-{run.district_code}
              </td>
              <td className="py-1.5 pr-2">
                <SyncedTables run={run} />
              </td>
              <td className="py-1.5 pr-2 text-gray-500">{formatDateTime(run.started_at)}</td>
              <td className="py-1.5 pr-2 text-gray-500">{formatDateTime(run.completed_at)}</td>
              <td className="py-1.5 pr-2 text-right tabular-nums">{run.processed_count ?? 0}</td>
              <td className="py-1.5 pr-2 text-right tabular-nums">{run.new_count ?? 0}</td>
              <td className="py-1.5 pr-2 text-right tabular-nums">{run.updated_count ?? 0}</td>
              <td className="py-1.5 pr-2 text-right tabular-nums">
                {run.deactivated_count ?? 0}
              </td>
              <td
                className={`py-1.5 pr-2 text-right tabular-nums ${
                  (run.failed_count ?? 0) > 0
                    ? "font-semibold text-red-600 dark:text-red-400"
                    : ""
                }`}
              >
                {run.failed_count ?? 0}
              </td>
              <td className="py-1.5 pr-2">
                {run.error_summary && Object.keys(run.error_summary).length > 0 ? (
                  <Distribution counts={run.error_summary} />
                ) : (
                  <span className="text-gray-400">-</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DbStatusPanel({
  status,
  error,
  loading,
  onRefresh,
}: {
  status: DbStatus | null;
  error: string | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-gray-950 dark:text-gray-50">장소 DB 상태</h2>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
            {status ? `${status.area_code}-${status.district_code}` : "-"} · 상세조회 TTL{" "}
            {status?.detail_ttl_days ?? "-"}일
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="rounded-md border border-gray-300 px-2.5 py-1 text-xs disabled:opacity-50 dark:border-gray-700"
        >
          {loading ? "불러오는 중…" : "새로고침"}
        </button>
      </header>

      {error && (
        <p className="mt-3 rounded-md bg-red-50 p-3 text-xs text-red-900 dark:bg-red-950/40 dark:text-red-100">
          {error}
        </p>
      )}

      {status && (
        <>
          <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-md bg-gray-100 p-2.5 dark:bg-gray-800">
              <dt className="text-[11px] text-gray-500 dark:text-gray-400">places 활성</dt>
              <dd className="text-lg font-bold tabular-nums">{status.places.active}</dd>
              <dd className="text-[11px] text-gray-500">
                전체 {status.places.total} · 비활성 {status.places.inactive}
              </dd>
            </div>
            <div className="rounded-md bg-gray-100 p-2.5 dark:bg-gray-800">
              <dt className="text-[11px] text-gray-500 dark:text-gray-400">
                place_enrichments
              </dt>
              <dd className="text-lg font-bold tabular-nums">
                {status.place_enrichments_count}
              </dd>
            </div>
            <div className="rounded-md bg-gray-100 p-2.5 dark:bg-gray-800">
              <dt className="text-[11px] text-gray-500 dark:text-gray-400">집중률 매핑</dt>
              <dd className="text-lg font-bold tabular-nums">
                {status.place_concentration_mappings_count}
              </dd>
            </div>
            <div className="rounded-md bg-gray-100 p-2.5 dark:bg-gray-800">
              <dt className="text-[11px] text-gray-500 dark:text-gray-400">
                최근 상세조회 시각
              </dt>
              <dd className="text-sm font-semibold">
                {formatDateTime(status.places.latest_detail_fetched_at)}
              </dd>
            </div>
          </dl>

          <dl className="mt-3 grid gap-2 sm:grid-cols-3">
            <div>
              <dt className="text-[11px] font-medium text-gray-500 dark:text-gray-400">
                상세조회 상태
              </dt>
              <dd className="mt-1">
                <Distribution counts={status.places.detail_fetch_status} />
              </dd>
            </div>
            <div>
              <dt className="text-[11px] font-medium text-gray-500 dark:text-gray-400">
                운영시간 파싱 상태
              </dt>
              <dd className="mt-1">
                <Distribution counts={status.places.operating_parse_status} />
              </dd>
            </div>
            <div>
              <dt className="text-[11px] font-medium text-gray-500 dark:text-gray-400">
                파서 버전
              </dt>
              <dd className="mt-1">
                <Distribution counts={status.places.operating_parser_version} />
              </dd>
            </div>
          </dl>

          <h3 className="mt-4 text-sm font-semibold text-gray-900 dark:text-gray-100">
            동기화 잠금
          </h3>
          {status.sync_locks.length === 0 ? (
            <p className="mt-1 text-xs text-gray-500">잠금 없음 — 실행 가능한 상태예요.</p>
          ) : (
            <ul className="mt-1">
              {status.sync_locks.map((lock) => (
                <LockRow key={lock.sync_run_id ?? `${lock.area_code}-${lock.district_code}`} lock={lock} />
              ))}
            </ul>
          )}

          <h3 className="mt-4 text-sm font-semibold text-gray-900 dark:text-gray-100">
            최근 동기화 이력
          </h3>
          <div className="mt-2">
            <SyncRunTable runs={status.sync_runs} />
          </div>
          <p className="mt-2 text-[11px] text-gray-500 dark:text-gray-400">
            장소 동기화가 쓰는 테이블은 places · place_sync_runs · place_sync_locks
            셋뿐이에요. place_enrichments와 집중률 매핑은 이 동기화가 건드리지 않아요
            (각각 별도 스크립트 소관).
          </p>
        </>
      )}
    </section>
  );
}
