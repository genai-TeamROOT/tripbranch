/*
 * 역할: 개발자가 /api/chat Agent Runtime 결과를 발화별로 검증하는 전용 채팅 화면.
 * 입력: 사용자 발화, TripContext 세션/감사 기록.
 * 출력: 가운데 채팅, 오른쪽 Agent Runtime Audit 패널.
 * 호출 시점: /dev-chat 라우트가 활성화될 때 호출된다.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  clearExchanges,
  fetchExchanges,
  setExchangeCapture,
  type ApiExchangeSnapshot,
} from "../api/dev";
import { fetchSessionState, streamChat, toDisplayConditions } from "../api/trip";
import { ChatComposer } from "../components/chat/ChatComposer";
import { ChatMessageList } from "../components/chat/ChatMessageList";
import { ApiExchangePanel } from "../components/dev/ApiExchangePanel";
import { DeveloperAuditPanel } from "../components/dev/DeveloperAuditPanel";
import { TurnLocationBadges } from "../components/dev/TurnLocationBadges";
import { ErrorBanner } from "../components/ErrorBanner";
import { AuthStatusBadge } from "../auth/AuthStatusBadge";
import { useTripDispatch, useTripState } from "../state/TripContext";
import { buildAgentStageTimings } from "../utils/agentTiming";
import { getLatestConversationPlaceName } from "../utils/conversationPlace";
import { getBrowserDeviceLocation } from "../utils/geolocation";
import {
  getLocationAgeMinutes,
  isLocationRefreshDue,
  LOCATION_RECONFIRM_AFTER_MS,
} from "../utils/locationRefresh";
import type { TravelOrigin } from "../types";

const REQUEST_MORE_PROMPT = "다른 곳 보여줘";
const RELAX_RADIUS_PROMPT = "검색 범위를 넓혀서 다시 추천해줘";
const STATUS_COMMAND = "/status";
interface PendingLocationRefresh {
  text: string;
  clarificationChoice?: string;
  travelOriginOverride?: TravelOrigin;
}

export function DeveloperChatPage() {
  const state = useTripState();
  const dispatch = useTripDispatch();
  const navigate = useNavigate();
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const previousAuditTurnCountRef = useRef(0);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [exchanges, setExchanges] = useState<ApiExchangeSnapshot | null>(null);
  const [exchangeError, setExchangeError] = useState<string | null>(null);
  // 개발자 채팅 전용 디버그 스위치. 켜두면 이후 모든 턴이 폐점 후보도 채점에
  // 포함한다 — no_data_closed 되묻기를 재현/우회하려고 매번 버튼을 누르지
  // 않아도 된다(실사용 피드백, 2026-08-13).
  const [debugIgnoreOperatingHours, setDebugIgnoreOperatingHours] = useState(false);
  const [pendingLocationRefresh, setPendingLocationRefresh] = useState<PendingLocationRefresh | null>(
    null,
  );

  const isLoading = state.phase === "interpreting" || state.phase === "recommending";
  const latestTurn = state.auditTurns.at(-1);

  const withExchangeErrors = useCallback(
    async (load: () => Promise<ApiExchangeSnapshot>) => {
      try {
        setExchanges(await load());
        setExchangeError(null);
      } catch (error) {
        setExchangeError(
          error instanceof ApiError
            ? error.message
            : "API 캡처 정보를 불러오지 못했어요.",
        );
      }
    },
    [],
  );

  const loadExchanges = useCallback(
    () => withExchangeErrors(fetchExchanges),
    [withExchangeErrors],
  );

  useEffect(() => {
    void loadExchanges();
  }, [loadExchanges]);

  useEffect(() => {
    const hasNewTurn = state.auditTurns.length > previousAuditTurnCountRef.current;
    previousAuditTurnCountRef.current = state.auditTurns.length;
    if (latestTurn && (selectedTurnId === null || hasNewTurn)) {
      setSelectedTurnId(latestTurn.id);
    }
  }, [latestTurn, selectedTurnId, state.auditTurns]);

  useEffect(() => {
    const scroller = chatScrollRef.current;
    if (!scroller) return;
    requestAnimationFrame(() => {
      if (typeof scroller.scrollTo === "function") {
        scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
        return;
      }
      scroller.scrollTop = scroller.scrollHeight;
    });
  }, [isLoading, state.messages.length]);

  const showStatus = useCallback(
    async (text: string) => {
      if (!state.session_id) {
        dispatch({
          type: "APPEND_SESSION_STATUS",
          payload: {
            userInput: text,
            status: null,
            error: "아직 세션이 없어요. 발화를 한 번 보낸 뒤에 다시 시도해주세요.",
          },
        });
        return;
      }
      try {
        const status = await fetchSessionState(state.session_id);
        dispatch({
          type: "APPEND_SESSION_STATUS",
          payload: { userInput: text, status, error: null },
        });
      } catch (error) {
        dispatch({
          type: "APPEND_SESSION_STATUS",
          payload: {
            userInput: text,
            status: null,
            error: error instanceof ApiError ? error.message : "세션 상태를 불러오지 못했어요.",
          },
        });
      }
    },
    [dispatch, state.session_id],
  );

  const send = useCallback(
    async (
      text: string,
      clarificationChoice?: string,
      deviceLocationOverride?: string,
      deviceLocationCapturedAt?: number,
      travelOriginOverride?: TravelOrigin,
    ) => {
      let deviceLocation = deviceLocationOverride ?? state.device_location;
      let capturedAt = deviceLocationCapturedAt;
      // /dev-chat은 HomePage를 거치지 않고 바로 들어올 수 있어 첫 턴엔 위치가 없다.
      // null로 계속 보내면 위치를 아예 모르는 채로만 테스트하게 돼 travel_origin
      // 같은 위치 기반 기능을 이 화면에서 확인할 수 없다 — 아직 없을 때만
      // HomePage와 같은 방식으로 한 번 가져온다. 이미 있으면(override든 이전
      // 턴에 저장된 값이든) 다시 묻지 않는다.
      if (deviceLocation === null) {
        try {
          deviceLocation = await getBrowserDeviceLocation();
          capturedAt = Date.now();
        } catch (error) {
          dispatch({
            type: "SET_ERROR",
            payload: error instanceof Error ? error.message : "위치를 가져오지 못했어요.",
          });
          return;
        }
      }
      const conversationPlaceName = getLatestConversationPlaceName(state.messages);
      dispatch({
        type: "START_CHAT_TURN",
        payload: { userInput: text, deviceLocation, deviceLocationCapturedAt: capturedAt },
      });
      const startedAt = performance.now();
      const progressEvents = [] as import("../types").AgentProgressEvent[];
      let messageStartElapsedMs: number | null = null;
      let firstMessageDeltaElapsedMs: number | null = null;
      let receivedStreamResult = false;
      let receivedStreamMessage = false;
      try {
        await streamChat(
          {
            user_input: text,
            session_id: state.session_id,
            device_location: deviceLocation,
            conversation_place_name: conversationPlaceName,
            clarification_choice: clarificationChoice ?? null,
            travel_origin_override: travelOriginOverride ?? null,
            debug_ignore_operating_hours: debugIgnoreOperatingHours,
          },
          (event) => {
            if (event.type === "progress") {
              progressEvents.push(event.data);
              dispatch({ type: "SET_AGENT_PROGRESS", payload: event.data });
              return;
            }
            if (event.type === "result") {
              receivedStreamResult = true;
              dispatch({
                type: "APPEND_STREAM_RESULT",
                payload: { ...event.data, elapsedMsClient: performance.now() - startedAt },
              });
              return;
            }
            if (event.type === "message_start") {
              receivedStreamMessage = true;
              messageStartElapsedMs = event.data.elapsed_ms;
              dispatch({ type: "START_STREAM_MESSAGE", payload: { intent: event.data.intent } });
              return;
            }
            if (event.type === "message_delta") {
              firstMessageDeltaElapsedMs ??= event.data.elapsed_ms;
              dispatch({ type: "APPEND_STREAM_MESSAGE_DELTA", payload: { text: event.data.text } });
              return;
            }
            if (event.type === "error") throw new ApiError(event.data);
            const response = event.data.response;
            const elapsedMsClient = performance.now() - startedAt;
            if (receivedStreamResult || receivedStreamMessage) {
              dispatch({
                type: "COMPLETE_STREAM_CHAT_TURN",
                payload: {
                  response,
                  elapsedMsClient,
                  serverElapsedMs: event.data.elapsed_ms,
                  stageTimings: buildAgentStageTimings(progressEvents, event.data.elapsed_ms, {
                    messageStartElapsedMs,
                    firstMessageDeltaElapsedMs,
                  }),
                  conditions: toDisplayConditions(response.llm_output),
                },
              });
              return;
            }
            dispatch({
              type: "APPEND_CHAT_TURN",
              payload: {
                userInput: text,
                intent: response.llm_output.intent,
                status: response.llm_output.status,
                conditions: toDisplayConditions(response.llm_output),
                mergedConditions: response.state.user_conditions,
                message: response.message,
                recommendations: response.recommendations,
                schedule: response.schedule,
                sessionId: response.state.session_id,
                agentResponse: response,
                showDebug: false,
                elapsedMsClient,
                ...(progressEvents.length > 0
                  ? {
                      serverElapsedMs: event.data.elapsed_ms,
                      stageTimings: buildAgentStageTimings(progressEvents, event.data.elapsed_ms, {
                        messageStartElapsedMs,
                        firstMessageDeltaElapsedMs,
                      }),
                    }
                  : {}),
              },
            });
          },
        );
      } catch (error) {
        const apiError = error instanceof ApiError ? error : null;
        dispatch({
          type: "APPEND_FAILED_CHAT_TURN",
          payload: {
            userInput: text,
            message: apiError?.message ?? "추천을 불러오지 못했어요. 다시 시도해주세요.",
            code: apiError?.code ?? "internal_server_error",
            retryable: apiError?.retryable ?? true,
            details: apiError?.details ?? null,
            elapsedMsClient: performance.now() - startedAt,
          },
        });
      } finally {
        // 외부 호출은 이 턴에서 발생하므로 턴이 끝난 직후에만 다시 읽는다.
        // 주기 폴링을 걸면 아무 일도 없는 동안 요청만 늘어난다.
        void loadExchanges();
      }
    },
    [
      debugIgnoreOperatingHours,
      dispatch,
      loadExchanges,
      state.device_location,
      state.messages,
      state.session_id,
    ],
  );

  const locationAgeMinutes = getLocationAgeMinutes(state.device_location_captured_at);

  const requestSend = useCallback(
    async (text: string, clarificationChoice?: string, travelOriginOverride?: TravelOrigin) => {
      if (
        isLocationRefreshDue(
          state.device_location,
          state.device_location_captured_at,
          state.device_location_snoozed_until,
        )
      ) {
        setPendingLocationRefresh({ text, clarificationChoice, travelOriginOverride });
        return;
      }
      await send(text, clarificationChoice, undefined, undefined, travelOriginOverride);
    },
    [
      send,
      state.device_location,
      state.device_location_captured_at,
      state.device_location_snoozed_until,
    ],
  );

  const usePreviousLocation = useCallback(() => {
    if (!pendingLocationRefresh) return;
    const pending = pendingLocationRefresh;
    setPendingLocationRefresh(null);
    // 실제 GPS는 다시 받지 않았으니 device_location_captured_at은 그대로 두고,
    // 재확인 질문만 30분 동안 미룬다 — 그래야 다음 턴 나이 표시가 실제 경과
    // 시간을 계속 정확히 보여준다(utils/locationRefresh.ts 참고).
    dispatch({
      type: "SNOOZE_LOCATION_REFRESH",
      payload: { until: Date.now() + LOCATION_RECONFIRM_AFTER_MS },
    });
    void send(pending.text, pending.clarificationChoice, undefined, undefined, pending.travelOriginOverride);
  }, [dispatch, pendingLocationRefresh, send]);

  const refreshBrowserLocation = useCallback(async () => {
    if (!pendingLocationRefresh) return;
    try {
      const deviceLocation = await getBrowserDeviceLocation({ forceFresh: true });
      const pending = pendingLocationRefresh;
      setPendingLocationRefresh(null);
      await send(
        pending.text,
        pending.clarificationChoice,
        deviceLocation,
        Date.now(),
        pending.travelOriginOverride,
      );
    } catch (error) {
      dispatch({
        type: "SET_ERROR",
        payload: error instanceof Error ? error.message : "현재 위치를 가져오지 못했어요.",
      });
    }
  }, [dispatch, pendingLocationRefresh, send]);

  async function handleFollowUp(text: string) {
    if (isLoading) return;
    if (text.trim() === STATUS_COMMAND) {
      await showStatus(text.trim());
      return;
    }
    await requestSend(text);
  }

  return (
    <main className="grid h-screen grid-cols-[380px_minmax(0,1fr)_480px] overflow-hidden bg-white text-gray-950 dark:bg-gray-950 dark:text-gray-50">
      <ApiExchangePanel
        snapshot={exchanges}
        error={exchangeError}
        onToggleCapture={(enabled) =>
          void withExchangeErrors(() => setExchangeCapture(enabled))
        }
        onClear={() => void withExchangeErrors(clearExchanges)}
        onRefresh={() => void loadExchanges()}
      />

      <section className="flex min-h-0 min-w-0 flex-col overflow-hidden">
        <header className="flex items-center justify-between gap-3 border-b border-gray-200 px-5 py-4 dark:border-gray-800">
          <div>
            <h1 className="text-xl font-bold">TripBranch</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              개발자용 채팅 검증 화면
            </p>
          </div>
          <div className="flex items-center gap-2">
            <AuthStatusBadge />
            <button
              type="button"
              onClick={() => navigate("/dev-ops")}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700"
            >
              Ops 패널
            </button>
            <button
              type="button"
              onClick={() => navigate("/chat")}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700"
            >
              사용자 화면
            </button>
            <button
              type="button"
              onClick={() => {
                dispatch({ type: "RESET" });
                setSelectedTurnId(null);
              }}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700"
            >
              새 대화
            </button>
          </div>
        </header>

        <div ref={chatScrollRef} className="min-h-0 flex-1 overflow-auto px-5 py-5">
          {state.error && (
            <ErrorBanner
              message={state.error}
              onRetry={() => {
                if (state.user_input) void requestSend(state.user_input);
              }}
            />
          )}

          {state.messages.length === 0 ? (
            <div className="flex h-full items-center justify-center">
              <div className="max-w-md rounded-md border border-dashed border-gray-300 p-6 text-center dark:border-gray-700">
                <h2 className="text-lg font-semibold">첫 발화를 입력해 검증을 시작하세요.</h2>
                <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                  응답이 돌아오면 오른쪽에 Intent, 조건 병합, Tool/Scoring 요약이 턴별로
                  누적됩니다.
                </p>
              </div>
            </div>
          ) : (
            <ChatMessageList
              messages={state.messages}
              showDebug={false}
              isDeveloperView
              isLoading={isLoading}
              hasDeviceLocation={Boolean(state.device_location)}
              deviceLocation={state.device_location}
              onRequestMore={() => void requestSend(REQUEST_MORE_PROMPT)}
              onRelaxRadius={() => void requestSend(RELAX_RADIUS_PROMPT)}
              onSelectClarificationOption={(optionId, label) => void requestSend(label, optionId)}
              onToggleTravelOrigin={(toggle) => {
                const label =
                  toggle.alternative_origin === "search_center"
                    ? `${toggle.alternative_origin_name} 기준으로 다시 보기`
                    : "현재 위치 기준으로 다시 보기";
                void requestSend(label, undefined, toggle.alternative_origin);
              }}
              locationRefresh={
                pendingLocationRefresh
                  ? {
                      ageMinutes: locationAgeMinutes,
                      onUsePrevious: usePreviousLocation,
                      onRefreshLocation: () => void refreshBrowserLocation(),
                    }
                  : null
              }
              progress={state.agentProgress}
            />
          )}
        </div>

        <div className="border-t border-gray-200 p-4 dark:border-gray-800">
          {/*
            직전 턴이 실제로 쓴 위치. 오른쪽 감사 패널이 아니라 여기 두는 이유는 폭이다 —
            패널은 좁아 지명이 잘린다. 선택된 턴이 아니라 마지막 턴을 보여준다: 이 자리는
            채팅 흐름의 끝이라 바로 위 대화와 같은 턴을 가리켜야 한다.
          */}
          {latestTurn && <TurnLocationBadges turn={latestTurn} />}
          <ChatComposer disabled={isLoading} onSubmit={handleFollowUp} />
        </div>
      </section>

      <DeveloperAuditPanel
        turns={state.auditTurns}
        selectedTurnId={selectedTurnId}
        onSelectTurn={setSelectedTurnId}
        debugIgnoreOperatingHours={debugIgnoreOperatingHours}
        onToggleDebugIgnoreOperatingHours={setDebugIgnoreOperatingHours}
      />
    </main>
  );
}
