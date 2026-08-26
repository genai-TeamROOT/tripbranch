/*
 * 역할: 첫 사용자 질문을 입력받아 해석 API를 호출하고 채팅 흐름을 시작한다.
 * 입력: 질문 입력창의 user_input 문자열과 상황 버튼 선택.
 * 출력: TripContext 메시지/조건 저장, /chat 이동, 로딩/오류 상태.
 * 호출 시점: 사용자가 루트 화면에서 여행 상황을 제출할 때 호출된다.
 * TODO: 위치 권한과 추천 예시를 실제 서비스 데이터에 맞게 보강한다.
 */

import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { streamChat, toDisplayConditions } from "../api/trip";
import { ErrorBanner } from "../components/ErrorBanner";
import { VoiceInputButton } from "../components/chat/VoiceInputButton";
import { AuthStatusBadge } from "../auth/AuthStatusBadge";
import { LanguageSelector } from "../components/LanguageSelector";
import { useTripDispatch, useTripState } from "../state/TripContext";
import { buildAgentStageTimings } from "../utils/agentTiming";
import { getBrowserDeviceLocation } from "../utils/geolocation";

const HOME_TEXT = {
  ko: {
    subtitle: "지금 상황을 말해주면 바로 대체 장소를 찾아볼게요.",
    locationNotice: "추천 시작 시 브라우저가 위치 권한을 요청합니다. 허용한 위치는 현재 채팅 세션의 장소 탐색 기준으로 사용됩니다.",
    prompts: ["비를 피할 실내 장소가 필요해", "남은 시간이 1시간 정도야", "근처 카페나 박물관을 찾고 싶어"],
    placeholder: "예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어",
    voiceHelp: "마이크를 누르고 말하면, 말이 끝난 뒤 자동으로 전송합니다.",
    locating: "현재 위치 확인 중...",
    start: "추천 시작하기",
    developer: "개발자용으로 시작",
    locationError: "위치를 가져오지 못했어요.",
    requestError: "입력을 처리하지 못했어요. 다시 시도해주세요.",
  },
  en: {
    subtitle: "Tell us what you need, and we’ll find a place to visit in Seoul.",
    locationNotice: "Your browser will ask for location permission before starting. We use it as the search point for this chat session.",
    prompts: ["I need an indoor place to avoid the rain", "I have about one hour left", "Find a café or museum nearby"],
    placeholder: "For example: Find a museum or café near Gyeongbokgung where I can avoid the rain",
    voiceHelp: "Tap the microphone and we’ll send your speech after you finish speaking.",
    locating: "Getting your location...",
    start: "Start recommendations",
    developer: "Start in developer view",
    locationError: "We couldn’t get your location.",
    requestError: "We couldn’t process your request. Please try again.",
  },
} as const;

export function HomePage() {
  const dispatch = useTripDispatch();
  const state = useTripState();
  const navigate = useNavigate();
  const text = HOME_TEXT[state.language];

  const [userInput, setUserInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
    try {
      await streamChat(
        {
          user_input: trimmed,
          language: state.language,
          session_id: null,
          device_location: deviceLocation,
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
      );
    } catch (error) {
      dispatch({
        type: "SET_ERROR",
        payload:
          error instanceof ApiError
            ? error.message
            : text.requestError,
      });
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await startChat(userInput);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-5 px-4 py-10">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">TripBranch</h1>
          <div className="flex items-center gap-2">
            <LanguageSelector
              language={state.language}
              onChange={(language) => dispatch({ type: "SET_LANGUAGE", payload: language })}
            />
            <AuthStatusBadge />
          </div>
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {text.subtitle}
        </p>
      </div>

      <section className="rounded-md border border-gray-200 p-3 text-sm text-gray-700 dark:border-gray-700 dark:text-gray-300">
        {text.locationNotice}
      </section>

      <div className="flex flex-wrap gap-2">
        {text.prompts.map((prompt) => (
          <button
            key={prompt}
            type="button"
            disabled={isLoading}
            onClick={() => setUserInput(prompt)}
            className="rounded-full border border-gray-300 px-3 py-1.5 text-xs text-gray-700 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300"
          >
            {prompt}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <textarea
          value={userInput}
          onChange={(event) => setUserInput(event.target.value)}
          rows={5}
          placeholder={text.placeholder}
          className="w-full resize-none rounded-md border border-gray-300 p-3 text-sm focus:border-gray-500 focus:outline-none dark:border-gray-700 dark:bg-gray-900"
        />

        <div className="flex items-center gap-2">
          <VoiceInputButton
            disabled={isLoading}
            onTranscript={() => {
              setErrorMessage(null);
            }}
            onAutoSubmit={async (transcript) => {
              setErrorMessage(null);
              await startChat(transcript);
            }}
            onError={setErrorMessage}
          />
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {text.voiceHelp}
          </p>
        </div>

        {errorMessage && <ErrorBanner message={errorMessage} />}

        <button
          type="submit"
          disabled={isLoading || !userInput.trim()}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
        >
          {isLoading ? text.locating : text.start}
        </button>
        <button
          type="button"
          disabled={isLoading || !userInput.trim()}
          onClick={() => void startChat(userInput, "/dev-chat")}
          className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-800 disabled:opacity-50 dark:border-gray-700 dark:text-gray-100"
        >
          {text.developer}
        </button>
      </form>

    </main>
  );
}
