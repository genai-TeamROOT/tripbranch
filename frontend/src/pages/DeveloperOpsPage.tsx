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
  fetchSyncDistricts,
  fetchSyncJob,
  reconcilePlaces,
  resetApiUsage,
  type ApiUsageSnapshot,
  type DbStatus,
  type ReconcileResult,
  type SyncDistrict,
  type SyncDistricts,
  type SyncJob,
} from "../api/dev";
import { fetchFeedbackStats } from "../api/feedback";
import { fetchTraceStats } from "../api/trace";
import type { FeedbackStatsResponse, TraceStatsResponse } from "../types";
import { ApiUsagePanel } from "../components/dev/ApiUsagePanel";
import { DbStatusPanel } from "../components/dev/DbStatusPanel";
import { FeedbackStatsPanel } from "../components/dev/FeedbackStatsPanel";
import { PlaceSyncPanel } from "../components/dev/PlaceSyncPanel";
import { TracePanel } from "../components/dev/TracePanel";

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

  const [feedbackStats, setFeedbackStats] = useState<FeedbackStatsResponse | null>(null);
  const [feedbackStatsError, setFeedbackStatsError] = useState<string | null>(null);
  const [feedbackStatsLoading, setFeedbackStatsLoading] = useState(false);

  const loadFeedbackStats = useCallback(async () => {
    setFeedbackStatsLoading(true);
    try {
      setFeedbackStats(await fetchFeedbackStats());
      setFeedbackStatsError(null);
    } catch (error) {
      setFeedbackStatsError(toMessage(error, "피드백 통계를 불러오지 못했어요."));
    } finally {
      setFeedbackStatsLoading(false);
    }
  }, []);

  const [traceStats, setTraceStats] = useState<TraceStatsResponse | null>(null);
  const [traceStatsError, setTraceStatsError] = useState<string | null>(null);
  const [traceStatsLoading, setTraceStatsLoading] = useState(false);

  const loadTraceStats = useCallback(async () => {
    setTraceStatsLoading(true);
    try {
      setTraceStats(await fetchTraceStats());
      setTraceStatsError(null);
    } catch (error) {
      setTraceStatsError(toMessage(error, "Trace 통계를 불러오지 못했어요."));
    } finally {
      setTraceStatsLoading(false);
    }
  }, []);

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
  const [districts, setDistricts] = useState<SyncDistricts | null>(null);
  const [selectedDistrict, setSelectedDistrict] = useState<SyncDistrict | null>(null);

  const loadDistricts = useCallback(async () => {
    try {
      const next = await fetchSyncDistricts();
      setDistricts(next);
      // 처음 한 번만 고른다. 이후 새로고침이 사용자의 선택을 되돌리면 안 된다.
      setSelectedDistrict((current) => current ?? next.loaded[0] ?? null);
      setSyncError(null);
    } catch (error) {
      setSyncError(toMessage(error, "구 목록을 불러오지 못했어요."));
    }
  }, []);

  /* 구를 바꾸면 앞 구의 대조 결과와 job을 비운다. 남겨두면 중구를 대조한 화면에서
   * 용산구를 반영하는 조작이 가능해 보인다 — 서버가 거부하긴 하지만, 화면이 그런
   * 조작을 제안하는 것 자체가 잘못이다. */
  const handleSelectDistrict = useCallback((district: SyncDistrict) => {
    setSelectedDistrict(district);
    setReconcile(null);
    setJob(null);
    setSyncError(null);
  }, []);

  const handleReconcile = useCallback(async () => {
    if (!selectedDistrict) return;
    setReconciling(true);
    try {
      setReconcile(
        await reconcilePlaces({
          areaCode: selectedDistrict.area_code,
          districtCode: selectedDistrict.district_code,
        }),
      );
      setSyncError(null);
    } catch (error) {
      setSyncError(toMessage(error, "대조에 실패했어요."));
    } finally {
      setReconciling(false);
    }
  }, [selectedDistrict]);

  const handleApply = useCallback(
    async (input: {
      confirm: string;
      includeExcluded: boolean;
      detailsLimit: number | null;
    }) => {
      if (!reconcile) return;
      setApplying(true);
      try {
        const started = await applyPlaceSync({
          // 구는 대조 결과에서 가져온다 — 드롭다운은 그 사이 바뀔 수 있고,
          // 반영은 어디까지나 이 스냅샷이 담고 있는 구에 대한 것이다.
          areaCode: reconcile.area_code,
          districtCode: reconcile.district_code,
          snapshot: reconcile.snapshot,
          /* 못 채운 건을 함께 보낸다. 서버가 알아서 더하기도 하지만, 보내지
           * 않으면 job 파라미터의 대상 수가 화면이 예고한 수와 어긋난다. */
          detailContentIds: [
            ...reconcile.detail_content_ids,
            ...(input.includeExcluded ? reconcile.detail_excluded_ids : []),
            ...reconcile.detail_backfill_ids,
          ],
          addedContentIds: reconcile.rows
            .filter((row) => row.change_type === "added")
            .map((row) => row.content_id),
          // 패널은 항상 실제 반영이다. dry-run은 한도를 똑같이 쓰면서 결과를
          // 남기지 않아, 모르고 켜두면 "돌렸는데 아무것도 안 바뀜"이 된다.
          dryRun: false,
          detailsLimit: input.detailsLimit,
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
    void loadDistricts();
    void loadFeedbackStats();
    void loadTraceStats();
  }, [loadDbStatus, loadDistricts, loadFeedbackStats, loadTraceStats, loadUsage]);

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
          // 끝났으면 DB 상태를 다시 읽어 반영 결과를 화면에 맞춘다. 구 목록도
          // 함께 읽는다 — 이번에 처음 적재한 구는 여기서부터 건수가 생긴다.
          void loadDbStatus();
          void loadDistricts();
        }
      } catch (error) {
        setSyncError(toMessage(error, "job 상태를 불러오지 못했어요."));
      }
    }, JOB_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [jobId, loadDbStatus, loadDistricts]);

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
          districts={districts}
          selected={selectedDistrict}
          reconcile={reconcile}
          job={job}
          error={syncError}
          reconciling={reconciling}
          applying={applying}
          /* 잔여를 계산하지 않는 이유: 이 값도 하한이다. 재시도가 안 세지고,
           * 완료 처리를 못 한 실행은 사용량이 비어 있다. 한도에서 빼면 실제보다
           * 여유가 있는 것처럼 보인다. */
          detailCallsToday={dbStatus?.detail_calls_today ?? null}
          onSelectDistrict={handleSelectDistrict}
          onReconcile={() => void handleReconcile()}
          onApply={(input) => void handleApply(input)}
        />
        <DbStatusPanel
          status={dbStatus}
          error={dbError}
          loading={dbLoading}
          onRefresh={() => void loadDbStatus()}
        />
        <FeedbackStatsPanel
          stats={feedbackStats}
          error={feedbackStatsError}
          loading={feedbackStatsLoading}
          onRefresh={() => void loadFeedbackStats()}
        />
        <TracePanel
          stats={traceStats}
          error={traceStatsError}
          loading={traceStatsLoading}
          onRefresh={() => void loadTraceStats()}
        />
      </div>
    </main>
  );
}
