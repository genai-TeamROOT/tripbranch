/*
 * 역할: 첫 사용자 질문을 입력받아 해석 API를 호출하고 채팅 흐름을 시작한다.
 * 입력: 컴포저의 user_input 문자열과 상황 버튼 선택.
 * 출력: TripContext 메시지/조건 저장, /chat 이동, 로딩/오류 상태.
 * 호출 시점: 사용자가 루트 화면에서 여행 상황을 제출할 때 호출된다.
 * TODO: 위치 권한과 추천 예시를 실제 서비스 데이터에 맞게 보강한다.
 * 근거: package_D/DESIGN_SYSTEM.md §10.1·§10.5.
 *
 * ChatPage와 같은 ChatComposer를 쓴다 — Figma가 홈도 채팅형 하단 고정 바를 쓰기
 * 때문이다. 상황 예시 칩은 입력창을 채우기만 하고 전송하지 않는다(§10.5) —
 * "개발자용으로 시작"도 같은 텍스트로 고를 수 있어야 해서다.
 */

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { streamChat, toDisplayConditions } from "../api/trip";
import { ChatComposer } from "../components/chat/ChatComposer";
import { ErrorBanner } from "../components/ErrorBanner";
import { AppHeader } from "../components/layout/AppHeader";
import { usePhotoSimilarSearch } from "../hooks/usePhotoSimilarSearch";
import { beginChatRequest, endChatRequest, wasCancelledByUser } from "../state/chatAbortController";
import { loadPreferences } from "../state/preferenceStorage";
import {
  loadLocationSettings,
  syncLocationSettingsFromConditions,
} from "../state/locationSettings";
import { useLocationSettings } from "../hooks/useLocationSettings";
import { syncPreferences } from "../state/preferenceSync";
import { useTripDispatch, useTripState } from "../state/TripContext";
import { buildAgentStageTimings } from "../utils/agentTiming";
import { getBrowserDeviceLocation } from "../utils/geolocation";

const HOME_TEXT = {
  ko: {
    headline: "갑자기 일정이 바뀌셨나요?",
    subtitle: "지금 상황을 말해주면 바로 대체 장소를 찾아볼게요.",
    locationNotice:
      "추천 시작 시 브라우저가 위치 권한을 요청합니다. 허용한 위치는 현재 채팅 세션의 장소 탐색 기준으로 사용됩니다.",
    prompts: [
      "비를 피할 실내 장소가 필요해",
      "남은 시간이 1시간 정도야",
      "근처 카페나 박물관을 찾고 싶어",
    ],
    placeholder: "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    start: "추천 시작하기",
    developer: "개발자용으로 시작",
    locationError: "위치를 가져오지 못했어요.",
    requestError: "입력을 처리하지 못했어요. 다시 시도해주세요.",
    myPreferences: "내 취향",
    changePreferences: "바꾸기",
  },
  en: {
    headline: "Did your plans change suddenly?",
    subtitle: "Tell us what you need, and we’ll find a place to visit in Seoul.",
    locationNotice:
      "Your browser will ask for location permission before starting. We use it as the search point for this chat session.",
    prompts: [
      "I need an indoor place to avoid the rain",
      "I have about one hour left",
      "Find a café or museum nearby",
    ],
    placeholder: "For example: Find a museum or café near Gyeongbokgung where I can avoid the rain",
    start: "Start recommendations",
    developer: "Start in developer view",
    locationError: "We couldn’t get your location.",
    requestError: "We couldn’t process your request. Please try again.",
    myPreferences: "My preferences",
    changePreferences: "Change",
  },
} as const;

export function HomePage() {
  const dispatch = useTripDispatch();
  const state = useTripState();
  const navigate = useNavigate();
  const text = HOME_TEXT[state.language];

  /*
   * 저장해 둔 취향. 이 기기 값으로 먼저 그리고 계정 값으로 맞춘다 — 로딩 표시를
   * 두지 않는 이유는 대부분 둘이 같아 깜빡임만 남기 때문이다. 다른 기기에서 바꾼
   * 경우에만 줄이 바뀌고, 그때는 바뀌는 것이 맞다.
   */
  const locationSettings = useLocationSettings();
  const [preferences, setPreferences] = useState(loadPreferences);

  useEffect(() => {
    let active = true;
    void syncPreferences().then((synced) => {
      if (active) setPreferences(synced);
    });
    return () => {
      active = false;
    };
  }, []);

  const [userInput, setUserInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const searchByPhoto = usePhotoSimilarSearch();

  /*
   * ChatPage와 같은 훅을 쓴다(usePhotoSimilarSearch). searchByPhoto는 호출되자마자
   * (첫 await 전까지) 대화에 메시지를 동기적으로 추가한다 — 그 뒤에 이동해야
   * ChatPage의 hasConversation 가드가 "대화 없음"으로 보고 홈으로 되돌리지
   * 않는다(먼저 이동부터 하면 메시지가 아직 없어 튕겨 나간다).
   */
  async function handlePhotoSelect(file: File) {
    const pending = searchByPhoto(file);
    navigate("/chat");
    await pending;
  }

  async function startChat(input: string, targetPath = "/chat") {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    setIsLoading(true);
    setErrorMessage(null);

    let deviceLocation: string;
    try {
      // 사용자 동작 직후 호출해야 브라우저가 위치 권한 팝업을 정상적으로 표시한다.
      deviceLocation = await getBrowserDeviceLocation();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : text.locationError);
      setIsLoading(false);
      return;
    }

    // 위치 확보 직후 채팅 화면으로 이동한다. 응답을 기다리는 동안 A→B→C→D 처리
    // 단계를 동적으로 보여주고, /api/chat 완료 시 실제 결과로 교체한다.
    dispatch({ type: "RESET" });
    dispatch({
      type: "START_CHAT_TURN",
      payload: {
        userInput: trimmed,
        deviceLocation,
        deviceLocationCapturedAt: Date.now(),
      },
    });
    navigate(targetPath);

    const startedAt = performance.now();
    const progressEvents = [] as import("../types").AgentProgressEvent[];
    let messageStartElapsedMs: number | null = null;
    let firstMessageDeltaElapsedMs: number | null = null;
    let receivedStreamResult = false;
    let receivedStreamMessage = false;
    // 발화를 보내자마자 /chat으로 이동하므로(위), 실제 요청은 이 화면이 언마운트된
    // 뒤에도 계속 진행된다 — ChatPage의 "중단" 버튼이 닿을 수 있도록 이 요청도
    // 같은 전역 컨트롤러에 등록한다(state/chatAbortController.ts).
    const controller = beginChatRequest();
    try {
      await streamChat(
        {
          user_input: trimmed,
          language: state.language,
          session_id: null,
          device_location: deviceLocation,
          selected_search_center: loadLocationSettings().center,
          selected_current_location: loadLocationSettings().origin,
        },
        (event) => {
          if (event.type === "progress") {
            progressEvents.push(event.data);
            dispatch({ type: "SET_AGENT_PROGRESS", payload: event.data });
            return;
          }
          /* 조건 병합 직후에 온다 — 도구 조회·채점·답변 스트리밍보다 앞이라,
             발화로 위치를 바꾸면 결과를 기다리지 않고 상단 칩이 먼저 바뀐다. */
          if (event.type === "location_resolved") {
            syncLocationSettingsFromConditions(event.data);
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
            // done 뒤에 오는 유일한 이벤트다. 첫 턴은 여기서 /chat으로 넘어간 뒤에
            // 도착할 수 있는데, TripContext가 라우터 위에 있어 그대로 반영된다.
            dispatch({
              type: "APPEND_FOLLOW_UP_SUGGESTIONS",
              payload: { suggestions: event.data.suggestions },
            });
            return;
          }
          if (event.type === "error") throw new ApiError(event.data);

          const response = event.data.response;
          /* 위 location_resolved의 백스톱이다. SSE를 못 쓰는 환경은 단발 API로
             낮춰 done만 받으므로(streamChat의 catch), 그 경로에는 위 이벤트가
             아예 없다. 값이 같으면 헬퍼가 아무것도 쓰지 않아 두 번 불러도
             무해하다. 두 dispatch 분기 앞에 두어 스트리밍이든 아니든 지나간다. */
          syncLocationSettingsFromConditions(response.state.user_conditions);
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
              userInput: trimmed,
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
        // ChatPage와 같은 이유다 — "중단" 버튼일 때만 뒷정리한다.
        if (wasCancelledByUser(controller)) dispatch({ type: "CANCEL_CHAT_TURN" });
        return;
      }
      dispatch({
        type: "SET_ERROR",
        payload: error instanceof ApiError ? error.message : text.requestError,
      });
    } finally {
      endChatRequest(controller);
    }
  }

  /*
   * ChatPage와 같은 계산이다(같은 세션 조건이 아직 남아 있으면 홈으로 돌아와도
   * 보여준다) — 브라우저 뒤로가기로 대화가 있던 홈에 돌아오는 경우가 그렇다.
   * "홈"을 새로 눌렀다면 사이드바 goHome()이 RESET을 먼저 보내 이 값도 비운다.
   * 아직 해석된 지명이 없으면(첫 진입) 실제 서비스 지원 지역인 "종로구"를
   * 기본값으로 쓴다 — 헤더에 위치 버튼이 항상 보여야 한다.
   */
  /* 위치 설정 화면의 칩과 같은 사다리를 본다 — 두 화면이 같은 사실을 말해야 한다.
     검색 기준을 비워두면 출발지가, 그것도 없으면 기기 좌표가 검색 중심이 된다
     (agent_context/service.py).

     설정이 아무것도 없을 때만 직전 턴이 해석한 위치로 떨어진다 — 대화가 이미
     있으면 서버가 그 위치를 들고 있어서 다음 발화도 거기서 찾는다.

     예전 기본값이던 "종로구"는 뺐다. 지원 지역이 종로구뿐이던 시절의 값이라
     지금은 사실이 아니고, 아무것도 모를 때 실제로 쓰이는 것은 기기 좌표다. */
  const locationLabel =
    locationSettings.center ??
    locationSettings.origin ??
    state.interpreted_conditions?.location_query ??
    "현재 위치";

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader locationLabel={locationLabel} />

      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-5 px-4 pb-4 pt-2">
        <div className="flex items-center justify-end">
          {/* 채우기만 하고 전송은 안 한다(§10.5) — 입력이 있어야 의미 있어
              비어 있으면 비활성. */}
          <button
            type="button"
            disabled={isLoading || !userInput.trim()}
            onClick={() => void startChat(userInput, "/dev-chat")}
            className="rounded-full bg-chip px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-sky-light disabled:opacity-50"
          >
            {text.developer}
          </button>
        </div>

        <div className="flex flex-col gap-2">
          <h1 className="text-[24px] font-bold leading-snug text-ink">{text.headline}</h1>
          <p className="text-sm leading-relaxed text-muted">{text.subtitle}</p>
        </div>

        {/*
         * 저장해 둔 취향을 여기서 한 번 더 보여준다 — 확인하려고 취향 설정
         * 화면까지 들어갔다 오지 않아도 되게. 읽기 전용이고, 고치려면 "바꾸기"로
         * 간다(홈에서 실수로 지우는 일을 만들지 않는다).
         *
         * 아직 아무것도 저장하지 않았으면 줄 자체를 그리지 않는다. 빈 자리를
         * 남기면 홈 첫 화면이 그만큼 밀린다.
         */}
        {preferences.length > 0 && (
          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold text-label">{text.myPreferences}</h2>
              <Link
                to="/preferences"
                className="text-xs font-bold text-brand transition-colors hover:text-brand-deep"
              >
                {text.changePreferences}
              </Link>
            </div>
            <ul className="flex flex-wrap gap-2">
              {preferences.map((preference) => (
                <li
                  key={preference.label}
                  className="rounded-full bg-chip px-3 py-1.5 text-xs font-medium text-brand-deep"
                >
                  {preference.label}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="rounded-2xl bg-sky-light p-3.5 text-sm leading-relaxed text-brand-deep">
          {text.locationNotice}
        </section>

        {errorMessage && <ErrorBanner message={errorMessage} />}

        <div className="flex flex-wrap items-start gap-3">
          {text.prompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              disabled={isLoading}
              onClick={() => setUserInput(prompt)}
              className="rounded-full bg-white px-4 py-2.5 text-left text-sm font-medium text-ink shadow-resting transition-colors hover:bg-chip disabled:opacity-50"
            >
              {prompt}
            </button>
          ))}
        </div>
      </div>

      <ChatComposer
        disabled={isLoading}
        value={userInput}
        onChange={setUserInput}
        onSubmit={async (submitted) => {
          setErrorMessage(null);
          await startChat(submitted);
        }}
        placeholder={text.placeholder}
        language={state.language}
        sendLabel={text.start}
        onPhotoSelect={handlePhotoSelect}
      />
    </main>
  );
}
