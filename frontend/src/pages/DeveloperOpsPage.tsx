/*
 * 역할: 개발자가 외부 API 호출량과 장소 DB 상태를 한 화면에서 확인하는 운영 패널.
 * 입력: /api/dev/api-usage, /api/dev/db-status.
 * 출력: 호출량 패널과 DB 상태 패널.
 * 호출 시점: /dev-ops 라우트가 활성화될 때 호출된다.
 *
 * /dev-chat의 Audit 패널은 발화 한 턴을 보지만 이 화면은 서버 전역·누적 상태를
 * 본다. 스코프가 달라 화면을 나눴다.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  applyPlaceSync,
  fetchApiUsage,
  fetchDbStatus,
  fetchSyncJob,
  reconcilePlaces,
  resetApiUsage,
  type ApiUsageSnapshot,
  type DbStatus,
  type ReconcileResult,
  type SyncJob,
} from "../api/dev";
import { ApiUsagePanel } from "../components/dev/ApiUsagePanel";
import { DbStatusPanel } from "../components/dev/DbStatusPanel";
import { PlaceSyncPanel } from "../components/dev/PlaceSyncPanel";

const AUTO_REFRESH_INTERVAL_MS = 3000;
const JOB_POLL_INTERVAL_MS = 1000;

function toMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    // 라우터는 APP_ENV=local일 때만 등록된다 — 404는 "서버가 로컬 모드가 아님"이다.
    if (error.code === "invalid_request") {
      return "개발자 API를 찾을 수 없어요. 백엔드가 APP_ENV=local로 떠 있는지 확인하세요.";
    }
    return error.message;
  }
  return fallback;
}

export function DeveloperOpsPage() {
  const navigate = useNavigate();
  const [usage, setUsage] = useState<ApiUsageSnapshot | null>(null);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const [dbStatus, setDbStatus] = useState<DbStatus | null>(null);
  const [dbError, setDbError] = useState<string | null>(null);
  const [dbLoading, setDbLoading] = useState(false);

  const loadUsage = useCallback(async () => {
    try {
      setUsage(await fetchApiUsage());
      setUsageError(null);
    } catch (error) {
      setUsageError(toMessage(error, "호출량을 불러오지 못했어요."));
    }
  }, []);

  const loadDbStatus = useCallback(async () => {
    setDbLoading(true);
    try {
      setDbStatus(await fetchDbStatus());
      setDbError(null);
    } catch (error) {
      setDbError(toMessage(error, "DB 상태를 불러오지 못했어요."));
    } finally {
      setDbLoading(false);
    }
  }, []);

  const [reconcile, setReconcile] = useState<ReconcileResult | null>(null);
  const [job, setJob] = useState<SyncJob | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [reconciling, setReconciling] = useState(false);
  const [applying, setApplying] = useState(false);

  const handleReconcile = useCallback(async () => {
    setReconciling(true);
    try {
      setReconcile(await reconcilePlaces());
      setSyncError(null);
    } catch (error) {
      setSyncError(toMessage(error, "대조에 실패했어요."));
    } finally {
      setReconciling(false);
    }
  }, []);

  const handleApply = useCallback(
    async (input: { dryRun: boolean; confirm: string; includeExcluded: boolean }) => {
      if (!reconcile) return;
      setApplying(true);
      try {
        const started = await applyPlaceSync({
          snapshot: reconcile.snapshot,
          detailContentIds: input.includeExcluded
            ? [...reconcile.detail_content_ids, ...reconcile.detail_excluded_ids]
            : reconcile.detail_content_ids,
          addedContentIds: reconcile.rows
            .filter((row) => row.change_type === "added")
            .map((row) => row.content_id),
          dryRun: input.dryRun,
          confirm: input.confirm,
        });
        setJob(started);
        setSyncError(null);
      } catch (error) {
        setSyncError(toMessage(error, "반영을 시작하지 못했어요."));
      } finally {
        setApplying(false);
      }
    },
    [reconcile],
  );

  const handleReset = useCallback(async () => {
    try {
      setUsage(await resetApiUsage());
      setUsageError(null);
    } catch (error) {
      setUsageError(toMessage(error, "카운터를 초기화하지 못했어요."));
    }
  }, []);

  useEffect(() => {
    void loadUsage();
    void loadDbStatus();
  }, [loadDbStatus, loadUsage]);

  // 폴링은 호출량에만 건다. DB 상태는 844행을 훑어 Supabase 호출이 따라붙으므로
  // 3초마다 부르면 패널 자체가 트래픽을 만든다.
  const loadUsageRef = useRef(loadUsage);
  loadUsageRef.current = loadUsage;
  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      void loadUsageRef.current();
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [autoRefresh]);

  // 실행 중인 job은 1초마다 확인한다. 진행률은 서버 메모리에만 있어(place_sync_runs
  // 행은 시작·종료만 남는다) 폴링 말고는 알 방법이 없다.
  const jobId = job?.status === "running" ? job.job_id : null;
  useEffect(() => {
    if (!jobId) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await fetchSyncJob(jobId);
        setJob(next);
        if (next.status !== "running") {
          // 끝났으면 DB 상태를 다시 읽어 반영 결과를 화면에 맞춘다.
          void loadDbStatus();
        }
      } catch (error) {
        setSyncError(toMessage(error, "job 상태를 불러오지 못했어요."));
      }
    }, JOB_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [jobId, loadDbStatus]);

  // 반영 다이얼로그에 참고용으로 넘길 detailIntro2 관측 사용량. 잔여를 계산하지
  // 않는 이유: 이 집계는 프로세스 메모리라 재시작 전 호출과 backend/scripts
  // 실행분이 빠져 있다. 한도에서 빼면 실제보다 여유가 있는 것처럼 보인다.
  const detailUsedSinceStart =
    usage?.entries.find(
      (entry) => entry.provider === "tour_api" && entry.operation === "detailIntro2",
    )?.today_count ?? null;

  return (
    <main className="min-h-screen bg-gray-50 text-gray-950 dark:bg-gray-950 dark:text-gray-50">
      <header className="flex items-center justify-between gap-3 border-b border-gray-200 bg-white px-5 py-4 dark:border-gray-800 dark:bg-gray-900">
        <div>
          <h1 className="text-xl font-bold">TripBranch Ops</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            외부 API 호출량 · 장소 DB 상태 (로컬 전용)
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => navigate("/dev-chat")}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700"
          >
            개발자 채팅
          </button>
          <button
            type="button"
            onClick={() => navigate("/chat")}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700"
          >
            사용자 화면
          </button>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-5">
        <ApiUsagePanel
          snapshot={usage}
          error={usageError}
          autoRefresh={autoRefresh}
          onToggleAutoRefresh={setAutoRefresh}
          onRefresh={() => void loadUsage()}
          onReset={() => void handleReset()}
        />
        <PlaceSyncPanel
          reconcile={reconcile}
          job={job}
          error={syncError}
          reconciling={reconciling}
          applying={applying}
          detailUsedSinceStart={detailUsedSinceStart}
          onReconcile={() => void handleReconcile()}
          onApply={(input) => void handleApply(input)}
        />
        <DbStatusPanel
          status={dbStatus}
          error={dbError}
          loading={dbLoading}
          onRefresh={() => void loadDbStatus()}
        />
      </div>
    </main>
  );
}
