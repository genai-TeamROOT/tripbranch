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

import { ChevronDown, ChevronUp } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { fetchSessionState, streamChat, toDisplayConditions } from "../api/trip";
import { ChatComposer } from "../components/chat/ChatComposer";
import { ChatMessageList } from "../components/chat/ChatMessageList";
import { SavedPlacesBar } from "../components/chat/SavedPlacesBar";
import { useAutoScrollToBottom } from "../hooks/useAutoScrollToBottom";
import { useScrollEdgeButton } from "../hooks/useScrollEdgeButton";
import { ErrorBanner } from "../components/ErrorBanner";
import { AppHeader } from "../components/layout/AppHeader";
import { usePhotoSimilarSearch } from "../hooks/usePhotoSimilarSearch";
import { useSavedPlaces } from "../hooks/useSavedPlaces";
import {
  beginChatRequest,
  cancelChatRequest,
  endChatRequest,
  wasCancelledByUser,
} from "../state/chatAbortController";
import { loadSearchCenter } from "../state/searchCenterStorage";
import { useTripDispatch, useTripState } from "../state/TripContext";
import type { TravelOrigin } from "../types";
import { buildAgentStageTimings } from "../utils/agentTiming";
import { getLatestConversationPlaceName } from "../utils/conversationPlace";
import { getBrowserDeviceLocation } from "../utils/geolocation";
import {
  getLocationAgeMinutes,
  isLocationRefreshDue,
  LOCATION_RECONFIRM_AFTER_MS,
} from "../utils/locationRefresh";

/*
 * 로컬 테스트용 슬래시 명령. Agent에 보내지 않고 GET /api/state/{session_id}로
 * 현재 누적 조건을 조회해 화면에만 표시한다. 커밋하지 않는 확인용 경로다.
 */
const STATUS_COMMAND = "/status";

const CHAT_TEXT = {
  ko: {
    developer: "개발자용 보기",
    requestError: "추천을 불러오지 못했어요. 다시 시도해주세요.",
    composer: "추가 조건을 입력해 주세요",
    clarificationComposer: "예: 경복궁 근처에서 찾아줘",
    requestMore: "다른 곳 보여줘",
    relaxRadius: "검색 범위를 넓혀서 다시 추천해줘",
    basedOn: (name: string) => `${name} 기준으로 다시 보기`,
    currentLocation: "현재 위치 기준으로 다시 보기",
  },
  en: {
    developer: "Developer view",
    requestError: "We couldn’t load recommendations. Please try again.",
    composer: "Add another condition or ask a follow-up",
    clarificationComposer: "For example: Find somewhere near Gyeongbokgung",
    requestMore: "Show more places",
    relaxRadius: "Search in a wider area",
    basedOn: (name: string) => `View results based on ${name}`,
    currentLocation: "View results based on my current location",
  },
} as const;
interface PendingLocationRefresh {
  text: string;
  clarificationChoice?: string;
  travelOriginOverride?: TravelOrigin;
}

export function ChatPage() {
  const state = useTripState();
  const dispatch = useTripDispatch();
  const navigate = useNavigate();
  const text = CHAT_TEXT[state.language];

  const isLoading = state.phase === "interpreting" || state.phase === "recommending";
  const hasConversation = state.messages.length > 0;
  const messagesContainerRef = useRef<HTMLDivElement | null>(null);
  useAutoScrollToBottom(messagesContainerRef, isLoading);
  const { isNearTop, isScrollable, scrollToTop, scrollToBottom } =
    useScrollEdgeButton(messagesContainerRef);
  const [pendingLocationRefresh, setPendingLocationRefresh] =
    useState<PendingLocationRefresh | null>(null);

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

  // 새로고침 직후 보관함을 서버 기준으로 다시 맞춘다(useSavedPlaces.ts 참고).
  const { refreshIfAny: refreshSavedIfAny } = useSavedPlaces();

  const send = useCallback(
    async (
      text: string,
      clarificationChoice?: string,
      deviceLocationOverride?: string,
      deviceLocationCapturedAt?: number,
      travelOriginOverride?: TravelOrigin,
      /*
       * 위치 인자가 이미 다섯이라 여섯 번째를 또 붙이면 호출부에서
       * `send(t, undefined, undefined, undefined, undefined, true)`가 된다.
       * 이후 확장은 이 객체에 담는다.
       */
      options?: { scheduleFromSaved?: boolean },
    ) => {
      const deviceLocation = deviceLocationOverride ?? state.device_location;
      const conversationPlaceName = getLatestConversationPlaceName(state.messages);
      dispatch({
        type: "START_CHAT_TURN",
        payload: {
          userInput: text,
          deviceLocation: deviceLocationOverride,
          deviceLocationCapturedAt,
        },
      });
      // 사용자가 입력하거나 버튼을 누른 시점부터 결과를 dispatch할 때까지를 잰다.
      const startedAt = performance.now();
      const progressEvents = [] as import("../types").AgentProgressEvent[];
      let messageStartElapsedMs: number | null = null;
      let firstMessageDeltaElapsedMs: number | null = null;
      let receivedStreamResult = false;
      let receivedStreamMessage = false;
      const controller = beginChatRequest();
      try {
        await streamChat(
          {
            user_input: text,
            language: state.language,
            session_id: state.session_id,
            device_location: deviceLocation,
            selected_search_center: loadSearchCenter(),
            conversation_place_name: conversationPlaceName,
            clarification_choice: clarificationChoice ?? null,
            travel_origin_override: travelOriginOverride ?? null,
            schedule_from_saved: options?.scheduleFromSaved ?? false,
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
            if (event.type === "follow_ups") {
              // done 뒤에 오는 유일한 이벤트다. 턴은 이미 끝나 로딩이 사라진
              // 상태이고, 버튼만 조금 늦게 붙는다.
              dispatch({
                type: "APPEND_FOLLOW_UP_SUGGESTIONS",
                payload: { suggestions: event.data.suggestions },
              });
              return;
            }
            if (event.type === "error") {
              throw new ApiError(event.data);
            }
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
                conditions: toDisplayConditions(response.llm_output),
                mergedConditions: response.state.user_conditions,
                message: response.message,
                recommendations: response.recommendations,
                schedule: response.schedule,
                sessionId: response.state.session_id,
                status: response.llm_output.status,
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
          controller.signal,
        );
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          // 끊긴 이유가 두 가지다. "중단" 버튼이면 오던 말풍선을 거기까지 얼려
          // 남기고(§7.2), 지난 대화를 열어 밀려난 것이면 아무것도 건드리지
          // 않는다 — 화면에는 이미 다른 대화가 그려져 있다.
          if (wasCancelledByUser(controller)) dispatch({ type: "CANCEL_CHAT_TURN" });
          return;
        }
        dispatch({
          type: "SET_ERROR",
          payload:
            error instanceof ApiError ? error.message : CHAT_TEXT[state.language].requestError,
        });
      } finally {
        endChatRequest(controller);
      }
      // 이 턴에서 거절이 일어났다면 서버가 보관함에서도 뺐다(saved ∩ rejected = ∅).
      // 그 결과는 AgentResponse.state(StateApplyResponse)에 실려 오지 않으므로
      // 여기서 다시 읽는다. 담긴 것이 없으면 호출 자체를 건너뛴다.
      await refreshSavedIfAny();
    },
    [
      dispatch,
      refreshSavedIfAny,
      state.device_location,
      state.language,
      state.messages,
      state.session_id,
    ],
  );

  /*
   * 보관함 CTA. 인텐트 분류를 건너뛰도록 schedule_from_saved만 세우고, user_input에는
   * 버튼 label을 채운다 — 채팅 이력에 "무엇을 눌렀는지"가 남아야 하기 때문이다.
   *
   * requestSend가 아니라 send를 직접 부른다. 위치 재확인 게이트는 GPS 나이가
   * 기준인데, 이 턴이 쓰는 좌표는 담을 때 찍힌 스냅샷이라 지금 위치를 다시
   * 받아도 편성 결과가 달라지지 않는다.
   */
  const planFromSaved = useCallback(() => {
    const label = state.language === "en" ? "Plan a trip with these" : "이 장소들로 일정 짜기";
    void send(label, undefined, undefined, undefined, undefined, { scheduleFromSaved: true });
  }, [send, state.language]);

  const handlePhotoSelect = usePhotoSimilarSearch();

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
    void send(
      pending.text,
      pending.clarificationChoice,
      undefined,
      undefined,
      pending.travelOriginOverride,
    );
  }, [dispatch, pendingLocationRefresh, send]);

  const refreshBrowserLocation = useCallback(async () => {
    if (!pendingLocationRefresh) return;
    try {
      // 버튼 클릭이라는 사용자 제스처 안에서 호출해야 브라우저가 위치 권한을 다시 요청할 수 있다.
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

  if (!hasConversation) {
    return <Navigate to="/" replace />;
  }

  async function handleFollowUp(text: string) {
    if (isLoading) return;
    if (text.trim() === STATUS_COMMAND) {
      await showStatus(text.trim());
      return;
    }
    await requestSend(text);
  }

  const locationLabel = state.interpreted_conditions?.location_query ?? "종로구";

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader locationLabel={locationLabel} />

      <div
        ref={messagesContainerRef}
        className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 px-4 pb-4"
      >
        {/* 브랜드 표기·언어 전환·신원 표시는 사이드바가 맡는다(DESIGN_SYSTEM.md
            6.17). "처음부터"는 사이드바 "홈"과 동작이 같아 중복이라 뺐다.
            화면 설명 문구도 뺐다 — 무엇을 하는 화면인지는 대화 자체로 드러난다. */}
        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={() => navigate("/dev-chat")}
            className="rounded-full bg-chip px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-sky-light"
          >
            {text.developer}
          </button>
        </div>

        {state.error && (
          <ErrorBanner
            message={state.error}
            onRetry={() => {
              if (state.user_input) void requestSend(state.user_input);
            }}
          />
        )}

        <ChatMessageList
          messages={state.messages}
          showDebug={false}
          isLoading={isLoading}
          deviceLocation={state.device_location}
          onRequestMore={() => void requestSend(text.requestMore)}
          onRelaxRadius={() => void requestSend(text.relaxRadius)}
          onSelectClarificationOption={(optionId, label) => void requestSend(label, optionId)}
          // 되묻기 버튼과 달리 override 없이 문구만 보낸다 — 사용자가 직접 입력한
          // 것과 같은 경로로 분류를 태운다.
          onSelectFollowUpSuggestion={(suggestion) => void handleFollowUp(suggestion)}
          onToggleTravelOrigin={(toggle) => {
            const label =
              toggle.alternative_origin === "search_center"
                ? text.basedOn(toggle.alternative_origin_name)
                : text.currentLocation;
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
          language={state.language}
        />

        <SavedPlacesBar
          onPlanFromSaved={planFromSaved}
          isLoading={isLoading}
          language={state.language}
        />
      </div>

      {isScrollable && (
        <div className="pointer-events-none sticky bottom-20 z-30 mx-auto flex w-full max-w-2xl justify-end px-4 md:bottom-24">
          <button
            type="button"
            onClick={isNearTop ? scrollToBottom : scrollToTop}
            aria-label={isNearTop ? "대화 맨 아래로 이동" : "대화 맨 위로 이동"}
            className="pointer-events-auto flex h-10 w-10 items-center justify-center rounded-full border border-white bg-white/60 text-ink shadow-resting backdrop-blur-md transition-colors hover:bg-white/80"
          >
            {isNearTop ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
          </button>
        </div>
      )}

      <ChatComposer
        disabled={isLoading}
        onSubmit={handleFollowUp}
        onCancel={isLoading ? cancelChatRequest : undefined}
        placeholder={state.awaiting_clarification ? text.clarificationComposer : text.composer}
        language={state.language}
        onPhotoSelect={handlePhotoSelect}
      />
    </main>
  );
}
