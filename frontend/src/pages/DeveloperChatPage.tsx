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
import { fetchSessionState, sendChat, toDisplayConditions } from "../api/trip";
import { ChatComposer } from "../components/chat/ChatComposer";
import { ChatMessageList } from "../components/chat/ChatMessageList";
import { ApiExchangePanel } from "../components/dev/ApiExchangePanel";
import { DeveloperAuditPanel } from "../components/dev/DeveloperAuditPanel";
import { ErrorBanner } from "../components/ErrorBanner";
import { useTripDispatch, useTripState } from "../state/TripContext";

const REQUEST_MORE_PROMPT = "다른 곳 보여줘";
const RELAX_RADIUS_PROMPT = "검색 범위를 넓혀서 다시 추천해줘";
const STATUS_COMMAND = "/status";

export function DeveloperChatPage() {
  const state = useTripState();
  const dispatch = useTripDispatch();
  const navigate = useNavigate();
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const previousAuditTurnCountRef = useRef(0);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [exchanges, setExchanges] = useState<ApiExchangeSnapshot | null>(null);
  const [exchangeError, setExchangeError] = useState<string | null>(null);

  const isLoading = state.phase === "interpreting" || state.phase === "recommending";

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
    const latestTurn = state.auditTurns.at(-1);
    const hasNewTurn = state.auditTurns.length > previousAuditTurnCountRef.current;
    previousAuditTurnCountRef.current = state.auditTurns.length;
    if (latestTurn && (selectedTurnId === null || hasNewTurn)) {
      setSelectedTurnId(latestTurn.id);
    }
  }, [selectedTurnId, state.auditTurns]);

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
    async (text: string) => {
      dispatch({ type: "START_CHAT_TURN", payload: { userInput: text } });
      const startedAt = performance.now();
      try {
        const response = await sendChat({
          user_input: text,
          session_id: state.session_id,
          device_location: state.device_location,
        });
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
            elapsedMsClient: performance.now() - startedAt,
          },
        });
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
    [dispatch, loadExchanges, state.device_location, state.session_id],
  );

  async function handleFollowUp(text: string) {
    if (isLoading) return;
    if (text.trim() === STATUS_COMMAND) {
      await showStatus(text.trim());
      return;
    }
    await send(text);
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
          <div className="flex gap-2">
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
                if (state.user_input) void send(state.user_input);
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
              showIntentBadges
              isLoading={isLoading}
              hasDeviceLocation={Boolean(state.device_location)}
              deviceLocation={state.device_location}
              onRequestMore={() => void send(REQUEST_MORE_PROMPT)}
              onRelaxRadius={() => void send(RELAX_RADIUS_PROMPT)}
            />
          )}
        </div>

        <div className="border-t border-gray-200 p-4 dark:border-gray-800">
          <ChatComposer disabled={isLoading} onSubmit={handleFollowUp} />
        </div>
      </section>

      <DeveloperAuditPanel
        turns={state.auditTurns}
        selectedTurnId={selectedTurnId}
        onSelectTurn={setSelectedTurnId}
      />
    </main>
  );
}
