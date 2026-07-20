/*
 * 역할: 사용자 입력과 추천 결과를 시간순 메시지로 누적하는 채팅 화면.
 * 입력: TripContext의 메시지/조건/phase와 후속 입력 이벤트.
 * 출력: ChatMessageList, 오류 배너, 하단 ChatComposer.
 * 호출 시점: /chat 라우트가 활성화되고 대화 상태가 있을 때 호출된다.
 * TODO: 실제 세션 ID와 스트리밍 응답이 생기면 메시지 append 경로를 확장한다.
 */

import { useCallback, useEffect, useRef } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { getRecommendations, interpretUserInput } from "../api/trip";
import { ChatComposer } from "../components/chat/ChatComposer";
import { ChatMessageList } from "../components/chat/ChatMessageList";
import { ErrorBanner } from "../components/ErrorBanner";
import { featureFlags } from "../config/features";
import { useTripDispatch, useTripState } from "../state/TripContext";
import type { InterpretedConditions } from "../types";

const RADIUS_RELAXATION_STEP_KM = 0.5;

export function ChatPage() {
  const state = useTripState();
  const dispatch = useTripDispatch();
  const navigate = useNavigate();
  const autoRequestKeyRef = useRef<string | null>(null);

  const showDebug = featureFlags.showInterpretationDebug;
  const isLoading = state.phase === "interpreting" || state.phase === "recommending";
  const hasConversation = state.messages.length > 0 && state.interpreted_conditions !== null;
  const lastMessageType = state.messages.at(-1)?.type;

  const requestRecommendations = useCallback(
    async (conditions: InterpretedConditions, resetShown = false) => {
      dispatch({ type: "START_RECOMMENDATIONS", payload: { conditions } });
      try {
        const result = await getRecommendations({
          ...conditions,
          shown_place_ids: resetShown ? [] : state.shown_place_ids,
        });
        dispatch({ type: "APPEND_RECOMMENDATIONS", payload: result });
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
    [dispatch, state.shown_place_ids],
  );

  useEffect(() => {
    if (
      !hasConversation ||
      showDebug ||
      state.phase !== "recommending" ||
      !state.interpreted_conditions ||
      lastMessageType !== "interpretation_summary"
    ) {
      return;
    }

    const requestKey = `${state.messages.length}-${state.interpreted_conditions.location_query}`;
    if (autoRequestKeyRef.current === requestKey) return;
    autoRequestKeyRef.current = requestKey;
    void requestRecommendations(state.interpreted_conditions);
  }, [
    hasConversation,
    lastMessageType,
    requestRecommendations,
    showDebug,
    state.interpreted_conditions,
    state.messages.length,
    state.phase,
  ]);

  if (!hasConversation) {
    return <Navigate to="/" replace />;
  }

  async function handleFollowUp(text: string) {
    if (isLoading) return;
    dispatch({ type: "START_INTERPRETING" });
    try {
      const conditions = await interpretUserInput(text);
      dispatch({
        type: "ADD_INTERPRETATION",
        payload: {
          userInput: text,
          conditions,
          showDebug,
        },
      });
    } catch (error) {
      dispatch({
        type: "SET_ERROR",
        payload:
          error instanceof ApiError
            ? error.message
            : "입력을 처리하지 못했어요. 다시 시도해주세요.",
      });
    }
  }

  function handleConfirmDebug(conditions: InterpretedConditions) {
    dispatch({ type: "MARK_DEBUG_CONFIRMED" });
    void requestRecommendations(conditions);
  }

  function handleRequestMore() {
    if (!state.interpreted_conditions) return;
    void requestRecommendations(state.interpreted_conditions);
  }

  function handleRelaxRadius() {
    if (!state.interpreted_conditions) return;
    const nextConditions = {
      ...state.interpreted_conditions,
      search_radius_km: state.interpreted_conditions.search_radius_km + RADIUS_RELAXATION_STEP_KM,
    };
    dispatch({
      type: "UPDATE_CONDITIONS",
      payload: { search_radius_km: nextConditions.search_radius_km },
    });
    void requestRecommendations(nextConditions, true);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-4 px-4 py-6">
      <header className="flex items-center justify-between gap-3 border-b border-gray-200 pb-4 dark:border-gray-800">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">TripBranch</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">대화형 대체 장소 추천</p>
        </div>
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
      </header>

      {state.error && (
        <ErrorBanner
          message={state.error}
          onRetry={() => {
            if (state.interpreted_conditions) void requestRecommendations(state.interpreted_conditions);
          }}
        />
      )}

      <ChatMessageList
        messages={state.messages}
        showDebug={showDebug}
        isLoading={isLoading}
        onConfirmDebug={handleConfirmDebug}
        onRequestMore={handleRequestMore}
        onRelaxRadius={handleRelaxRadius}
      />

      <ChatComposer disabled={isLoading} onSubmit={handleFollowUp} />
    </main>
  );
}
