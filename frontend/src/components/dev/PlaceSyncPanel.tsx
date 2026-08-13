/*
 * 역할: 장소 DB 동기화를 대조 → 반영 두 단계로 실행한다.
 * 입력: /api/dev/place-sync/{reconcile,apply,jobs}.
 * 출력: 대조 결과 표, 예상 호출수, 확인 다이얼로그, 진행바, 결과 카드.
 * 호출 시점: DeveloperOpsPage가 렌더링될 때.
 *
 * 대조는 목록 API 1회로 스냅샷을 남기고 비교만 한다(DB 안 건드림). 반영은 그
 * 대조가 정한 대상에만 상세조회를 보낸다. 한 버튼으로 합치면 무엇이 바뀌는지
 * 모르는 채로 운영 DB에 쓰게 된다.
 */

import { useState } from "react";
import type { ReconcileResult, ReconcileRow, SyncJob } from "../../api/dev";

const CHANGE_LABELS: Record<ReconcileRow["change_type"], string> = {
  added: "신규",
  removed: "삭제",
  updated: "수정",
};

const CHANGE_TONES: Record<ReconcileRow["change_type"], string> = {
  added: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100",
  removed: "bg-red-100 text-red-900 dark:bg-red-950/50 dark:text-red-100",
  updated: "bg-amber-100 text-amber-900 dark:bg-amber-950/50 dark:text-amber-100",
};

const PHASE_LABELS: Record<string, string> = {
  list: "목록 수집",
  upsert: "목록 반영",
  reparse: "운영시간 재파싱",
  details: "상세조회",
  deactivate: "비활성화",
  done: "완료",
};

function ChangeRows({ rows }: { rows: ReconcileRow[] }) {
  if (rows.length === 0) {
    return <p className="text-xs text-gray-500">변경된 장소가 없습니다.</p>;
  }
  return (
    <div className="max-h-64 overflow-y-auto rounded-md border border-gray-200 dark:border-gray-800">
      <table className="w-full text-left text-xs">
        <tbody>
          {rows.map((row) => (
            <tr
              key={`${row.change_type}-${row.content_id}`}
              className="border-b border-gray-100 last:border-0 dark:border-gray-800/60"
            >
              <td className="w-14 py-1.5 pl-2">
                <span
                  className={`rounded px-1.5 py-0.5 font-semibold ${CHANGE_TONES[row.change_type]}`}
                >
                  {CHANGE_LABELS[row.change_type]}
                </span>
              </td>
              <td className="py-1.5 pr-2">{row.title}</td>
              <td className="py-1.5 pr-2 font-mono text-[11px] text-gray-400">
                {row.content_id}
              </td>
              <td className="py-1.5 pr-2 font-mono text-[11px] text-gray-500">
                {row.changed_columns.join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JobProgress({ job }: { job: SyncJob }) {
  const ratio = job.total > 0 ? Math.min(1, job.processed / job.total) : 0;
  const running = job.status === "running";
  return (
    <section className="mt-3 rounded-md border border-gray-200 p-3 dark:border-gray-800">
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold">
          {running ? "실행 중" : `종료: ${job.status}`} ·{" "}
          {PHASE_LABELS[job.phase] ?? job.phase}
          {job.params.dry_run ? " (dry-run)" : ""}
        </span>
        <span className="tabular-nums text-gray-500">
          {job.processed} / {job.total}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
        <div
          className={`h-full ${running ? "bg-blue-500" : "bg-emerald-500"}`}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      {job.error && (
        <p className="mt-2 rounded bg-red-50 p-2 text-xs text-red-900 dark:bg-red-950/40 dark:text-red-100">
          {job.error}
        </p>
      )}
      {job.unmapped_new_place_ids.length > 0 && (
        <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
          집중률 매핑이 없는 신규 장소 {job.unmapped_new_place_ids.length}건 (
          {job.unmapped_new_place_ids.slice(0, 5).join(", ")}
          {job.unmapped_new_place_ids.length > 5 ? " …" : ""}). 매핑이 없는 장소는 혼잡도
          조회를 <strong>건너뜁니다</strong> — 오류 없이 그 장소만 판정에서 빠져요.
          <code className="ml-1">python -m scripts.build_concentration_mappings</code> 를
          실행해 매핑을 갱신하세요. 이 동기화는 매핑 테이블을 건드리지 않아요.
        </p>
      )}
      {job.result && (
        <dl className="mt-2 grid grid-cols-3 gap-2 text-xs sm:grid-cols-6">
          {[
            ["처리", job.result.processed_count],
            ["신규", job.result.new_count],
            ["갱신", job.result.updated_count],
            ["비활성", job.result.deactivated_count],
            ["상세조회", job.result.detail_attempted_count],
            ["실패", job.result.failed_count],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded bg-gray-100 p-1.5 dark:bg-gray-800">
              <dt className="text-[11px] text-gray-500">{label}</dt>
              <dd className="font-semibold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

export function PlaceSyncPanel({
  reconcile,
  job,
  error,
  reconciling,
  applying,
  detailUsedSinceStart,
  onReconcile,
  onApply,
}: {
  reconcile: ReconcileResult | null;
  job: SyncJob | null;
  error: string | null;
  reconciling: boolean;
  applying: boolean;
  /** 이 서버 기동 이후 관측된 detailIntro2 호출수. 집계가 없으면 null.
   *
   * "잔여"가 아니다 — 프로세스 메모리 집계라 재시작 전 호출과 backend/scripts
   * 실행분이 빠져 있다. 잔여로 표기하면 실제보다 여유가 있는 것처럼 보인다. */
  detailUsedSinceStart: number | null;
  onReconcile: () => void;
  onApply: (input: { dryRun: boolean; confirm: string; includeExcluded: boolean }) => void;
}) {
  const [dryRun, setDryRun] = useState(true);
  const [includeExcluded, setIncludeExcluded] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [showDialog, setShowDialog] = useState(false);

  const expectedConfirm = reconcile
    ? `${reconcile.area_code}-${reconcile.district_code}`
    : "";
  const detailCount =
    (reconcile?.detail_content_ids.length ?? 0) +
    (includeExcluded ? (reconcile?.detail_excluded_ids.length ?? 0) : 0);
  const jobRunning = job?.status === "running";

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-gray-950 dark:text-gray-50">DB 갱신</h2>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
            1단계 대조는 목록 API 1회로 스냅샷만 남겨요 (DB 변경 없음). 2단계 반영은
            변경된 장소에만 상세조회를 보내요.
          </p>
        </div>
        <button
          type="button"
          onClick={onReconcile}
          disabled={reconciling || jobRunning}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-gray-700"
        >
          {reconciling ? "대조 중…" : "1. 스냅샷 대조"}
        </button>
      </header>

      <p className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
        <strong>일일 호출 한도를 크게 소모할 수 있어요.</strong> 상세조회는 장소 1건당
        TourAPI <code>detailIntro2</code> 1회예요. 변경분이 많으면 한 번의 반영으로
        오늘 한도(1,000회)가 소진돼 그 뒤로는 추천·상세조회가 전부 실패합니다. 다른
        테스트와 시연을 모두 끝낸 뒤 마지막에 실행하는 걸 권해요.
      </p>

      {error && (
        <p className="mt-3 rounded-md bg-red-50 p-3 text-xs text-red-900 dark:bg-red-950/40 dark:text-red-100">
          {error}
        </p>
      )}

      {reconcile && (
        <>
          <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
            스냅샷 <span className="font-mono">{reconcile.snapshot}</span> (
            {reconcile.snapshot_count}건) · 기준{" "}
            <span className="font-mono">{reconcile.baseline ?? "없음"}</span>
            {reconcile.baseline_count !== undefined && ` (${reconcile.baseline_count}건)`}
          </p>

          {reconcile.skipped_columns.length > 0 && (
            <p className="mt-2 rounded-md bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
              기준 스냅샷에 없는 열은 비교하지 않았어요:{" "}
              {reconcile.skipped_columns.join(", ")}. 이 열들은 "안 바뀐 것"이 아니라
              "안 본 것"이에요.
            </p>
          )}

          <dl className="mt-3 grid grid-cols-4 gap-2">
            {[
              ["신규", reconcile.counts.added],
              ["삭제", reconcile.counts.removed],
              ["수정", reconcile.counts.updated],
              ["상세조회 대상", reconcile.detail_content_ids.length],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-md bg-gray-100 p-2.5 dark:bg-gray-800">
                <dt className="text-[11px] text-gray-500 dark:text-gray-400">{label}</dt>
                <dd className="text-lg font-bold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>

          {reconcile.detail_excluded_ids.length > 0 && (
            <label className="mt-2 flex items-start gap-2 rounded-md bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
              <input
                type="checkbox"
                checked={includeExcluded}
                onChange={(event) => setIncludeExcluded(event.target.checked)}
                className="mt-0.5"
              />
              <span>
                상세조회 제외 {reconcile.detail_excluded_ids.length}건 — 수정시각
                (source_modified_at)은 그대로인데 다른 열만 바뀐 장소예요. 상세 내용은
                안 바뀌었다고 보고 detailIntro2를 아껴요. 체크하면 이 건들도 상세조회에
                포함합니다.
              </span>
            </label>
          )}

          <div className="mt-3">
            <ChangeRows rows={reconcile.rows} />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-gray-200 pt-3 dark:border-gray-800">
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(event) => setDryRun(event.target.checked)}
              />
              dry-run (DB에 쓰지 않음)
            </label>
            <span className="text-xs text-gray-500">
              예상 외부 호출: 목록 0회 + 상세조회 {detailCount}회
              {dryRun ? "" : " · DB 쓰기 있음"}
            </span>
            <button
              type="button"
              onClick={() => {
                setConfirm("");
                setShowDialog(true);
              }}
              disabled={applying || jobRunning}
              className="ml-auto rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
            >
              2. 반영 실행
            </button>
          </div>
        </>
      )}

      {job && <JobProgress job={job} />}

      {showDialog && reconcile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-lg bg-white p-5 dark:bg-gray-900">
            <h3 className="text-base font-bold">
              {dryRun ? "dry-run 실행" : "DB에 반영합니다"}
            </h3>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
              {dryRun
                ? "DB는 변경하지 않고 상세조회만 수행해요."
                : "운영 Supabase의 places 테이블을 실제로 변경해요. 삭제된 장소는 비활성화됩니다."}
            </p>
            <ul className="mt-3 space-y-1 text-xs text-gray-600 dark:text-gray-300">
              <li>· 스냅샷: {reconcile.snapshot}</li>
              <li>· 상세조회 {detailCount}회 (TourAPI detailIntro2)</li>
              <li>
                · 신규 {reconcile.counts.added} / 수정 {reconcile.counts.updated} / 삭제{" "}
                {reconcile.counts.removed}
              </li>
            </ul>
            <p className="mt-3 rounded bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
              이 실행으로 <code>detailIntro2</code> {detailCount}회를 씁니다 (한도
              1,000회).
              {detailUsedSinceStart !== null &&
                ` 이 서버 기동 이후 관측된 사용량은 ${detailUsedSinceStart}회예요.`}{" "}
              관측값은 하한이에요 — 서버 재시작 전 호출과 backend/scripts 실행분은
              포함되지 않으니, 실제 잔여는 이보다 적을 수 있어요.
            </p>
            <label className="mt-4 block text-xs text-gray-600 dark:text-gray-300">
              확인을 위해 <span className="font-mono font-bold">{expectedConfirm}</span>{" "}
              를 입력하세요.
              <input
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-700 dark:bg-gray-950"
              />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowDialog(false)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700"
              >
                취소
              </button>
              <button
                type="button"
                disabled={confirm.trim() !== expectedConfirm}
                onClick={() => {
                  setShowDialog(false);
                  onApply({ dryRun, confirm: confirm.trim(), includeExcluded });
                }}
                className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
              >
                실행
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
