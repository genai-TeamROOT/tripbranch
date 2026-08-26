/*
 * 역할: 채팅 메시지 배열을 시간순으로 렌더링한다.
 * 입력: ChatMessage 배열, 디버그 노출 여부, 추천 관련 콜백.
 * 출력: 사용자/assistant/디버그/추천 결과 메시지 UI.
 * 호출 시점: ChatPage가 대화 본문을 그릴 때 호출된다.
 * TODO: 메시지 타입이 늘어나면 타입별 렌더러를 별도 파일로 분리한다.
 *
 * isDeveloperView는 /dev-chat에서만 true다(DeveloperChatPage). Intent 배지뿐
 * 아니라 추천 결과의 지연시간(elapsed_ms/server_elapsed_ms) 노출도 이 플래그로
 * 통일한다 — 실사용자 화면(ChatPage/HomePage)에는 내부 지연시간 숫자를 보여줄
 * 이유가 없다(개발자용 정보가 실서비스 화면에 새던 문제를 정리함).
 */

import { useEffect, useState } from "react";
import type { AgentProgressEvent, ChatMessage, Language, TravelOriginToggle } from "../../types";
import { AgentProgressMessage } from "./AgentProgressMessage";
import { ClarificationMessage } from "./ClarificationMessage";
import { CompareResultCards } from "./CompareResultCards";
import { LocationRefreshMessage } from "./LocationRefreshMessage";
import { ConditionDebugMessage } from "./ConditionDebugMessage";
import { FeedbackButtons } from "./FeedbackButtons";
import { PlaceInfoCard } from "./PlaceInfoCard";
import { RecommendationResultMessage } from "./RecommendationResultMessage";
import { ScheduleResultMessage } from "./ScheduleResultMessage";
import { SessionStatusMessage } from "./SessionStatusMessage";
import { findTurnText } from "../../utils/turnText";

function StreamingDots({ language }: { language: Language }) {
  const loadingLabel = language === "en" ? "Generating a response" : "답변 생성 중";
  return (
    <span className="flex h-6 items-center gap-1.5" aria-label={loadingLabel} role="status">
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          aria-hidden="true"
          className="h-2 w-2 animate-bounce rounded-full bg-gray-400 dark:bg-gray-500"
          style={{ animationDelay: `${index * 150}ms`, animationDuration: "900ms" }}
        />
      ))}
      <span className="sr-only">{loadingLabel}</span>
    </span>
  );
}

function StreamingText({ text, streaming, language }: { text: string; streaming: boolean; language: Language }) {
  // Gemini는 단어·문장 단위 청크를 보내기도 한다. 화면에서는 청크 크기와 무관하게
  // 한 글자씩 이어 보여, 첫 텍스트가 도착한 뒤에도 생성 중이라는 감각을 유지한다.
  const [visibleText, setVisibleText] = useState(() => (streaming ? "" : text));

  useEffect(() => {
    if (!text.startsWith(visibleText)) {
      setVisibleText(streaming ? "" : text);
      return;
    }
    if (visibleText.length >= text.length) return;

    const timer = window.setInterval(() => {
      setVisibleText((current) =>
        current.length < text.length ? text.slice(0, current.length + 1) : current,
      );
    }, 18);
    return () => window.clearInterval(timer);
  }, [streaming, text, visibleText]);

  const displayText =
    language === "en" && text === "이런 곳들을 찾아봤어요:"
      ? "Here are some places that match your preferences."
      : visibleText;
  return <p className="whitespace-pre-line leading-6">{displayText}</p>;
}

interface ChatMessageListProps {
  messages: ChatMessage[];
  showDebug: boolean;
  isLoading: boolean;
  hasDeviceLocation: boolean;
  deviceLocation: string | null;
  isDeveloperView?: boolean;
  onRequestMore: () => void;
  onRelaxRadius: () => void;
  onSelectClarificationOption: (optionId: string, label: string) => void;
  onToggleTravelOrigin?: (toggle: TravelOriginToggle) => void;
  locationRefresh: {
    ageMinutes: number | null;
    onUsePrevious: () => void;
    onRefreshLocation: () => void;
  } | null;
  progress: AgentProgressEvent | null;
  language?: Language;
}

export function ChatMessageList({
  messages,
  showDebug,
  isLoading,
  hasDeviceLocation,
  deviceLocation,
  isDeveloperView = false,
  onRequestMore,
  onRelaxRadius,
  onSelectClarificationOption,
  onToggleTravelOrigin,
  locationRefresh,
  progress,
  language = "ko",
}: ChatMessageListProps) {
  return (
    <div className="flex flex-1 flex-col gap-4">
      {messages
        .filter((message) => showDebug || message.type !== "condition_debug")
        .map((message, index, renderedMessages) => {
          if (message.type === "user_text") {
            return (
              <p
                key={message.id}
                className="ml-auto max-w-xl rounded-md bg-gray-900 px-4 py-3 text-sm text-white dark:bg-gray-100 dark:text-gray-900"
              >
                {message.text}
              </p>
            );
          }

          if (message.type === "assistant_text" || message.type === "interpretation_summary") {
            return (
              <div
                key={message.id}
                className="mr-auto flex max-w-xl flex-col gap-2 rounded-md bg-gray-100 px-4 py-3 text-sm text-gray-800 dark:bg-gray-800 dark:text-gray-100"
              >
                {isDeveloperView && message.type === "assistant_text" && message.intent && (
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="rounded bg-gray-900 px-2 py-0.5 font-semibold text-white dark:bg-gray-100 dark:text-gray-900">
                      Intent: {message.intent}
                    </span>
                    {message.status && (
                      <span className="rounded border border-gray-300 px-2 py-0.5 text-gray-600 dark:border-gray-700 dark:text-gray-300">
                        {message.status}
                      </span>
                    )}
                  </div>
                )}
                {message.type === "assistant_text" && message.streaming && message.text === "…" ? (
                  <StreamingDots language={language} />
                ) : (
                  <StreamingText
                    text={message.text}
                    streaming={message.type === "assistant_text" && Boolean(message.streaming)}
                    language={language}
                  />
                )}
              </div>
            );
          }

          if (message.type === "condition_debug") {
            return (
              <ConditionDebugMessage
                key={message.id}
                userInput={message.userInput}
                conditions={message.conditions}
                mergedConditions={message.mergedConditions}
                deviceLocation={deviceLocation}
                intent={message.intent ?? null}
                status={message.status}
              />
            );
          }

          if (message.type === "session_status") {
            return (
              <SessionStatusMessage
                key={message.id}
                status={message.status}
                error={message.error}
              />
            );
          }

          if (message.type === "schedule_result") {
            return (
              <ScheduleResultMessage
                key={message.id}
                schedule={message.schedule}
                elapsedMs={message.elapsed_ms}
                showElapsedTime={isDeveloperView}
                isLoading={isLoading}
                onRequestMore={onRequestMore}
                onRelaxRadius={onRelaxRadius}
              />
            );
          }

          if (message.type === "place_info_result") {
            return <PlaceInfoCard key={message.id} card={message.card} />;
          }

          if (message.type === "compare_result") {
            return (
              <CompareResultCards
                key={message.id}
                comparison={message.comparison}
                deviceLocation={deviceLocation}
              />
            );
          }

          if (message.type === "feedback") {
            // "feedback" 메시지 자체에는 텍스트가 없다 — 바로 앞의 결과 카드를
            // 지나 그 턴의 user_text/assistant_text까지 거슬러 올라가 찾는다
            // (findTurnText는 카드/피드백 등 텍스트가 없는 메시지를 건너뛰고
            // 계속 탐색하므로 이 메시지의 index를 그대로 넘겨도 된다).
            const { userInput, assistantMessage, intent } = findTurnText(renderedMessages, index);
            return (
              <div key={message.id} className="mr-auto flex w-full max-w-2xl justify-end">
                <FeedbackButtons
                  sessionId={message.sessionId}
                  runId={message.runId}
                  userInput={userInput}
                  assistantMessage={assistantMessage}
                  intent={intent}
                />
              </div>
            );
          }

          if (message.type === "clarification") {
            return (
              <ClarificationMessage
                key={message.id}
                text={message.text}
                options={message.options}
                isLoading={isLoading}
                onSelectOption={onSelectClarificationOption}
              />
            );
          }

          return (
            <RecommendationResultMessage
              key={message.id}
              recommendations={message.recommendations}
              unverifiedRecommendations={message.unverified_recommendations}
              travelOriginToggle={message.travel_origin_toggle}
              elapsedMs={message.elapsed_ms}
              serverElapsedMs={message.server_elapsed_ms}
              showElapsedTime={isDeveloperView}
              isLoading={isLoading}
              onRequestMore={onRequestMore}
              onRelaxRadius={onRelaxRadius}
              onToggleTravelOrigin={onToggleTravelOrigin}
              language={language}
            />
          );
        })}
      {locationRefresh && (
        <LocationRefreshMessage
          ageMinutes={locationRefresh.ageMinutes}
          isLoading={isLoading}
          onUsePrevious={locationRefresh.onUsePrevious}
          onRefreshLocation={locationRefresh.onRefreshLocation}
        />
      )}
      {isLoading && (
        <AgentProgressMessage
          hasDeviceLocation={hasDeviceLocation}
          schedulePlanning={progress?.stage === "scheduling"}
          progress={progress}
          language={language}
        />
      )}
    </div>
  );
}
