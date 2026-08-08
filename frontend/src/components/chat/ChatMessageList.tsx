/*
 * 역할: 채팅 메시지 배열을 시간순으로 렌더링한다.
 * 입력: ChatMessage 배열, 디버그 노출 여부, 추천 관련 콜백.
 * 출력: 사용자/assistant/디버그/추천 결과 메시지 UI.
 * 호출 시점: ChatPage가 대화 본문을 그릴 때 호출된다.
 * TODO: 메시지 타입이 늘어나면 타입별 렌더러를 별도 파일로 분리한다.
 */

import type { ChatMessage } from "../../types";
import { AgentProgressMessage } from "./AgentProgressMessage";
import { ConditionDebugMessage } from "./ConditionDebugMessage";
import { RecommendationResultMessage } from "./RecommendationResultMessage";
import { ScheduleResultMessage } from "./ScheduleResultMessage";
import { SessionStatusMessage } from "./SessionStatusMessage";

interface ChatMessageListProps {
  messages: ChatMessage[];
  showDebug: boolean;
  isLoading: boolean;
  hasDeviceLocation: boolean;
  deviceLocation: string | null;
  showIntentBadges?: boolean;
  onRequestMore: () => void;
  onRelaxRadius: () => void;
}

export function ChatMessageList({
  messages,
  showDebug,
  isLoading,
  hasDeviceLocation,
  deviceLocation,
  showIntentBadges = false,
  onRequestMore,
  onRelaxRadius,
}: ChatMessageListProps) {
  return (
    <div className="flex flex-1 flex-col gap-4">
      {messages
        .filter((message) => showDebug || message.type !== "condition_debug")
        .map((message) => {
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
                {showIntentBadges && message.type === "assistant_text" && message.intent && (
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
                <p>{message.text}</p>
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
            return <ScheduleResultMessage key={message.id} schedule={message.schedule} />;
          }

          return (
            <RecommendationResultMessage
              key={message.id}
              recommendations={message.recommendations}
              unverifiedRecommendations={message.unverified_recommendations}
              elapsedMs={message.elapsed_ms}
              serverElapsedMs={message.server_elapsed_ms}
              isLoading={isLoading}
              onRequestMore={onRequestMore}
              onRelaxRadius={onRelaxRadius}
            />
          );
        })}
      {isLoading && <AgentProgressMessage hasDeviceLocation={hasDeviceLocation} />}
    </div>
  );
}
