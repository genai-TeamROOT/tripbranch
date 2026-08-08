/*
 * 역할: 사용자 입력과 추천 결과를 시간순 메시지로 누적하는 채팅 화면.
 * 입력: TripContext의 메시지/조건/phase와 후속 입력 이벤트.
 * 출력: ChatMessageList, 오류 배너, 하단 ChatComposer.
 * 호출 시점: /chat 라우트가 활성화되고 대화 상태가 있을 때 호출된다.
 *
 * 모든 발화는 /api/chat 한 번으로 처리된다 — Intent 분류·조건 병합·Tool 조회·
 * Scoring·메시지 조립을 Agent Runtime이 전부 수행하므로, 화면은 응답을 메시지로
 * 옮기기만 한다. "다른 장소 보기"/"검색 범위 넓히기"도 같은 경로로 자연어를 보낸다
 * (MODIFY Intent). 제외 목록의 단일 기준은 세션(B)이라 프론트가 따로 넘기지 않는다.
 * TODO: 스트리밍 응답이 생기면 메시지 append 경로를 확장한다.
 */

import { useCallback } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { fetchSessionState, sendChat, toDisplayConditions } from "../api/trip";
import { ChatComposer } from "../components/chat/ChatComposer";
import { ChatMessageList } from "../components/chat/ChatMessageList";
import { ErrorBanner } from "../components/ErrorBanner";
import { useTripDispatch, useTripState } from "../state/TripContext";

const REQUEST_MORE_PROMPT = "다른 곳 보여줘";
/*
 * Agent가 되묻기 맥락을 다음 턴에 넘기지 않아, "경복궁"처럼 짧은 답변은 INFO로
 * 분류돼 추천이 나오지 않는다. 발화를 대신 만들어 보내지 않고 예시만 안내한다.
 */
const CLARIFICATION_PLACEHOLDER = "예: 경복궁 근처에서 찾아줘";
const RELAX_RADIUS_PROMPT = "검색 범위를 넓혀서 다시 추천해줘";
/*
 * 로컬 테스트용 슬래시 명령. Agent에 보내지 않고 GET /api/state/{session_id}로
 * 현재 누적 조건을 조회해 화면에만 표시한다. 커밋하지 않는 확인용 경로다.
 */
const STATUS_COMMAND = "/status";

export function ChatPage() {
  const state = useTripState();
  const dispatch = useTripDispatch();
  const navigate = useNavigate();

  const isLoading = state.phase === "interpreting" || state.phase === "recommending";
  const hasConversation = state.messages.length > 0;

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
      // 사용자가 입력하거나 버튼을 누른 시점부터 결과를 dispatch할 때까지를 잰다.
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
            conditions: toDisplayConditions(response.llm_output),
            mergedConditions: response.state.user_conditions,
            message: response.message,
            recommendations: response.recommendations,
            sessionId: response.state.session_id,
            status: response.llm_output.status,
            agentResponse: response,
            showDebug: false,
            elapsedMsClient: performance.now() - startedAt,
          },
        });
      } catch (error) {
        dispatch({
          type: "SET_ERROR",
          payload:
            error instanceof ApiError
              ? error.message
              : "추천을 불러오지 못했어요. 다시 시도해주세요.",
        });
      }
    },
    [dispatch, state.device_location, state.session_id],
  );

  if (!hasConversation) {
    return <Navigate to="/" replace />;
  }

  async function handleFollowUp(text: string) {
    if (isLoading) return;
    if (text.trim() === STATUS_COMMAND) {
      await showStatus(text.trim());
      return;
    }
    await send(text);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-4 px-4 py-6">
      <header className="flex items-center justify-between gap-3 border-b border-gray-200 pb-4 dark:border-gray-800">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">TripBranch</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">대화형 대체 장소 추천</p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => navigate("/dev-chat")}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700"
          >
            개발자용 보기
          </button>
          <button
            type="button"
            onClick={() => {
              dispatch({ type: "RESET" });
              navigate("/");
            }}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700"
          >
            처음부터
          </button>
        </div>
      </header>

      {state.error && (
        <ErrorBanner
          message={state.error}
          onRetry={() => {
            if (state.user_input) void send(state.user_input);
          }}
        />
      )}

      <ChatMessageList
        messages={state.messages}
        showDebug={false}
        isLoading={isLoading}
        hasDeviceLocation={Boolean(state.device_location)}
        deviceLocation={state.device_location}
        onRequestMore={() => void send(REQUEST_MORE_PROMPT)}
        onRelaxRadius={() => void send(RELAX_RADIUS_PROMPT)}
      />

      <ChatComposer
        disabled={isLoading}
        onSubmit={handleFollowUp}
        placeholder={state.awaiting_clarification ? CLARIFICATION_PLACEHOLDER : undefined}
      />
    </main>
  );
}
