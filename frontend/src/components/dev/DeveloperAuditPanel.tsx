/*
 * 역할: /dev-chat 화면 오른쪽에서 발화별 Agent Runtime 실행 결과를 감사용으로 표시한다.
 * 입력: TripContext에 누적된 DeveloperAuditTurn 배열과 현재 선택된 turn id.
 * 출력: 발화 카드 목록, 선택 발화의 LLM/B/C/D/Raw JSON 상세.
 * 호출 시점: DeveloperChatPage가 개발자용 채팅 화면을 렌더링할 때 호출된다.
 */

import { useMemo, useState } from "react";
import type {
  DeveloperAuditTurn,
  LLMExecutionMetadata,
  RecommendationItem,
  UserConditions,
} from "../../types";

type AuditTab = "summary" | "llm" | "state" | "tools" | "scoring" | "raw";

const TABS: { id: AuditTab; label: string }[] = [
  { id: "summary", label: "요약" },
  { id: "llm", label: "LLM 추출" },
  { id: "state", label: "B 상태" },
  { id: "tools", label: "C Tool" },
  { id: "scoring", label: "D Scoring" },
  { id: "raw", label: "Raw JSON" },
];

const CONDITION_LABELS: [keyof UserConditions, string][] = [
  ["current_location", "현재 위치"],
  ["search_center", "검색 중심"],
  ["place_types", "장소 종류"],
  ["place_tags", "장소 태그"],
  ["weather", "날씨"],
  ["weather_intent", "날씨 의도"],
  ["concentration_intent", "혼잡도 의도"],
  ["transport", "이동 수단"],
  ["max_travel_time", "최대 이동 시간"],
  ["time_available", "가용 시간"],
  ["environment", "실내외"],
  ["companion", "동행"],
  ["budget", "예산"],
  ["exclude_tags", "제외 태그"],
  ["special_requirements", "특별 요구사항"],
];

function formatDuration(milliseconds: number | null | undefined) {
  if (typeof milliseconds !== "number" || !Number.isFinite(milliseconds)) return "-";
  return milliseconds >= 1000
    ? `${(milliseconds / 1000).toFixed(1)}초`
    : `${Math.round(milliseconds)}ms`;
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "없음";
  if (value === null || value === undefined || value === "") return "없음";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function compactJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function getRecommendationItems(turn: DeveloperAuditTurn): RecommendationItem[] {
  if (!turn.recommendations) return [];
  return [
    ...turn.recommendations.recommendations,
    ...turn.recommendations.unverified_recommendations,
  ];
}

function getConditionChanges(before: UserConditions | null, after: UserConditions | null) {
  if (!after) return [];
  return CONDITION_LABELS.filter(([key]) => {
    const beforeValue = before?.[key] ?? null;
    const afterValue = after[key] ?? null;
    return JSON.stringify(beforeValue) !== JSON.stringify(afterValue);
  }).map(([key, label]) => ({
    key,
    label,
    before: before?.[key] ?? null,
    after: after[key] ?? null,
  }));
}

function toLlmExecutionMetadata(value: unknown): LLMExecutionMetadata | null {
  if (!value || typeof value !== "object") return null;
  const calls = (value as { calls?: unknown }).calls;
  if (!Array.isArray(calls)) return null;
  return {
    calls: calls.flatMap((call) => {
      if (!call || typeof call !== "object") return [];
      const entry = call as Record<string, unknown>;
      if (typeof entry.operation !== "string" || !Array.isArray(entry.attempted_models)) return [];
      return [
        {
          operation: entry.operation,
          attempted_models: entry.attempted_models.filter(
            (model): model is string => typeof model === "string",
          ),
          served_model: typeof entry.served_model === "string" ? entry.served_model : null,
        },
      ];
    }),
  };
}

function getLlmExecution(turn: DeveloperAuditTurn): LLMExecutionMetadata | null {
  if (turn.response?.llm_execution) return turn.response.llm_execution;
  const details = turn.failure?.details;
  if (!details || typeof details !== "object") return null;
  return toLlmExecutionMetadata((details as { llm_execution?: unknown }).llm_execution);
}

function LlmExecutionCards({ execution }: { execution: LLMExecutionMetadata | null }) {
  if (!execution?.calls.length) {
    return (
      <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
        LLM 실행 모델 정보가 없습니다. Fake LLM 사용, LLM 호출 전 실패, 또는 이전 응답일 수
        있습니다.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {execution.calls.map((call, index) => {
        const usedFallback = call.attempted_models.length > 1;
        return (
          <section
            key={`${call.operation}-${index}`}
            className="rounded-md border border-gray-200 bg-white p-3 dark:border-gray-800 dark:bg-gray-900"
          >
            <p className="text-xs font-semibold text-gray-900 dark:text-gray-100">
              {index + 1}. {call.operation}
            </p>
            <p className="mt-2 text-xs text-gray-500">시도: {call.attempted_models.join(" → ")}</p>
            <p className="mt-1 text-xs text-gray-700 dark:text-gray-300">
              응답 모델: {call.served_model ?? "응답 없음(실패)"}
              {usedFallback ? " · 폴백 시도" : ""}
            </p>
          </section>
        );
      })}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-md border border-gray-200 p-3 dark:border-gray-800">
      <dt className="text-xs font-medium text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="mt-1 break-words text-sm text-gray-900 dark:text-gray-100">
        {formatValue(value)}
      </dd>
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-96 overflow-auto rounded-md bg-gray-950 p-3 text-xs text-gray-100">
      {compactJson(value)}
    </pre>
  );
}

interface DeveloperAuditPanelProps {
  turns: DeveloperAuditTurn[];
  selectedTurnId: string | null;
  onSelectTurn: (turnId: string) => void;
}

export function DeveloperAuditPanel({
  turns,
  selectedTurnId,
  onSelectTurn,
}: DeveloperAuditPanelProps) {
  const [activeTab, setActiveTab] = useState<AuditTab>("summary");
  const selectedTurn = turns.find((turn) => turn.id === selectedTurnId) ?? turns.at(-1) ?? null;
  const conditionChanges = useMemo(
    () =>
      selectedTurn
        ? getConditionChanges(selectedTurn.beforeConditions, selectedTurn.afterConditions)
        : [],
    [selectedTurn],
  );
  const llmExecution = selectedTurn ? getLlmExecution(selectedTurn) : null;

  return (
    <aside className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden border-l border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-950">
      <header className="border-b border-gray-200 px-5 py-4 dark:border-gray-800">
        <p className="text-xs font-semibold uppercase tracking-widest text-emerald-700 dark:text-emerald-400">
          TripBranch Developer Console
        </p>
        <h2 className="mt-1 text-lg font-bold text-gray-950 dark:text-gray-50">
          Agent Runtime Audit
        </h2>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              발화별 감사 기록
            </h3>
            <span className="text-xs text-gray-500">{turns.length}건</span>
          </div>

          {turns.length === 0 ? (
            <p className="rounded-md border border-dashed border-gray-300 p-4 text-sm text-gray-500 dark:border-gray-700">
              아직 실행된 발화가 없습니다. 가운데 채팅에서 질문을 보내면 이곳에 기록됩니다.
            </p>
          ) : (
            <div className="flex flex-col gap-2">
              {turns.map((turn, index) => {
                const isSelected = selectedTurn?.id === turn.id;
                return (
                  <button
                    key={turn.id}
                    type="button"
                    onClick={() => onSelectTurn(turn.id)}
                    className={`rounded-md border p-3 text-left transition ${
                      isSelected
                        ? "border-emerald-500 bg-white shadow-sm dark:bg-gray-900"
                        : "border-gray-200 bg-white hover:border-gray-300 dark:border-gray-800 dark:bg-gray-900"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="line-clamp-2 text-sm font-medium text-gray-950 dark:text-gray-50">
                        {index + 1}. {turn.userInput}
                      </p>
                      <span
                        className={`shrink-0 rounded px-2 py-0.5 text-xs font-semibold ${
                          turn.intent === "ERROR"
                            ? "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-100"
                            : "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-100"
                        }`}
                      >
                        {turn.intent}
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-gray-500">
                      {turn.status} · {formatDuration(turn.elapsedMsClient)} · 추천{" "}
                      {getRecommendationItems(turn).length}건
                    </p>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        {selectedTurn && (
          <section className="mt-5 flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={`rounded-md px-3 py-1.5 text-xs font-medium ${
                    activeTab === tab.id
                      ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
                      : "border border-gray-200 text-gray-600 dark:border-gray-800 dark:text-gray-300"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {activeTab === "summary" && (
              <dl className="grid grid-cols-2 gap-2">
                <DetailRow label="Intent" value={selectedTurn.intent} />
                <DetailRow label="Status" value={selectedTurn.status} />
                <DetailRow label="Session ID" value={selectedTurn.sessionId} />
                <DetailRow label="Run ID" value={selectedTurn.runId} />
                <DetailRow label="기기 GPS" value={selectedTurn.deviceLocation} />
                <DetailRow label="클라이언트 소요" value={formatDuration(selectedTurn.elapsedMsClient)} />
                <DetailRow label="서버 소요" value={formatDuration(selectedTurn.serverElapsedMs)} />
                <DetailRow label="추천 결과" value={`${getRecommendationItems(selectedTurn).length}건`} />
                <DetailRow
                  label="LLM 응답 모델"
                  value={llmExecution?.calls.map((call) => call.served_model ?? "실패").join(", ")}
                />
                <DetailRow
                  label="LLM 폴백"
                  value={llmExecution?.calls.some((call) => call.attempted_models.length > 1) ? "시도됨" : "없음"}
                />
                {selectedTurn.failure && (
                  <>
                    <DetailRow label="오류 코드" value={selectedTurn.failure.code} />
                    <DetailRow label="재시도 가능" value={selectedTurn.failure.retryable} />
                  </>
                )}
              </dl>
            )}

            {activeTab === "llm" && (
              <div className="flex flex-col gap-3">
                <DetailRow label="사용자 발화" value={selectedTurn.userInput} />
                <DetailRow
                  label={selectedTurn.failure ? "오류 메시지" : "챗봇 메시지"}
                  value={selectedTurn.message}
                />
                {selectedTurn.failure ? (
                  <>
                    <JsonBlock value={selectedTurn.failure} />
                    <LlmExecutionCards execution={llmExecution} />
                  </>
                ) : (
                  <>
                    <LlmExecutionCards execution={llmExecution} />
                    <JsonBlock value={selectedTurn.response?.llm_output} />
                  </>
                )}
              </div>
            )}

            {activeTab === "state" && (
              selectedTurn.response ? <div className="flex flex-col gap-3">
                <section className="rounded-md border border-gray-200 p-3 dark:border-gray-800">
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    이번 턴 조건 변경
                  </h4>
                  {conditionChanges.length === 0 ? (
                    <p className="mt-2 text-sm text-gray-500">변경된 누적 조건이 없습니다.</p>
                  ) : (
                    <dl className="mt-3 grid gap-2">
                      {conditionChanges.map((change) => (
                        <div key={change.key} className="rounded bg-gray-100 p-2 text-xs dark:bg-gray-900">
                          <dt className="font-semibold text-gray-700 dark:text-gray-200">
                            {change.label}
                          </dt>
                          <dd className="mt-1 text-gray-600 dark:text-gray-300">
                            {formatValue(change.before)} → {formatValue(change.after)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </section>
                <JsonBlock
                  value={{
                    user_conditions: selectedTurn.response.state.user_conditions,
                    applied_operations: selectedTurn.response.state.applied_operations ?? [],
                    ignored_operations: selectedTurn.response.state.ignored_operations ?? [],
                    reset_applied: selectedTurn.response.state.reset_applied,
                    condition_changed: selectedTurn.response.state.condition_changed,
                  }}
                />
              </div> : <p className="rounded-md border border-dashed border-gray-300 p-4 text-sm text-gray-500 dark:border-gray-700">LLM 또는 HTTP 오류로 B 상태 병합 전 요청이 중단됐습니다.</p>
            )}

            {activeTab === "tools" && (
              selectedTurn.response ? <div className="flex flex-col gap-3">
                <dl className="grid grid-cols-2 gap-2">
                  <DetailRow label="검색 중심" value={selectedTurn.afterConditions?.search_center} />
                  <DetailRow label="기기 GPS" value={selectedTurn.deviceLocation} />
                  <DetailRow label="API 날씨 캐시" value={selectedTurn.response.state.api_context?.api_weather} />
                  <DetailRow label="GPS 만료" value={selectedTurn.response.state.api_context?.gps_expired} />
                  <DetailRow label="날씨 만료" value={selectedTurn.response.state.api_context?.weather_expired} />
                  <DetailRow
                    label="혼잡도 보강 여부"
                    value={
                      selectedTurn.intent === "RECOMMEND" &&
                      (selectedTurn.afterConditions?.concentration_intent === "SEEK" ||
                        selectedTurn.afterConditions?.concentration_intent === "AVOID")
                        ? "요청 조건에 포함"
                        : "미대상 또는 응답 미제공"
                    }
                  />
                </dl>
                <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                  C의 원본 Tool 호출 목록과 raw 후보 수는 현재 AgentResponse에 포함되지 않아
                  표시하지 않습니다. 백엔드 debug 필드가 추가되면 이 탭에 바로 붙일 수 있습니다.
                </p>
              </div> : <p className="rounded-md border border-dashed border-gray-300 p-4 text-sm text-gray-500 dark:border-gray-700">LLM 단계에서 실패해 C Tool은 호출되지 않았습니다.</p>
            )}

            {activeTab === "scoring" && (
              <div className="flex flex-col gap-3">
                {getRecommendationItems(selectedTurn).length === 0 ? (
                  <p className="rounded-md border border-dashed border-gray-300 p-4 text-sm text-gray-500 dark:border-gray-700">
                    D Scoring 결과가 없습니다. INFO/GENERAL이거나 C 단계에서 후보가 없을 수 있습니다.
                  </p>
                ) : (
                  getRecommendationItems(selectedTurn).map((item, index) => (
                    <section
                      key={item.place_id}
                      className="rounded-md border border-gray-200 bg-white p-3 dark:border-gray-800 dark:bg-gray-900"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <h4 className="text-sm font-semibold text-gray-950 dark:text-gray-50">
                            {index + 1}. {item.name}
                          </h4>
                          <p className="text-xs text-gray-500">
                            {item.category} · {item.distance_km}km
                          </p>
                        </div>
                        <span className="rounded bg-gray-900 px-2 py-0.5 text-xs font-semibold text-white dark:bg-gray-100 dark:text-gray-900">
                          {item.score?.toFixed?.(3) ?? item.score}
                        </span>
                      </div>
                      <JsonBlock
                        value={{
                          feature_scores: item.feature_scores,
                          weights_used: item.weights_used,
                          explanations: item.explanations,
                          warnings: item.warnings,
                        }}
                      />
                    </section>
                  ))
                )}
              </div>
            )}

            {activeTab === "raw" && <JsonBlock value={selectedTurn.response ?? selectedTurn.failure} />}
          </section>
        )}
      </div>
    </aside>
  );
}
