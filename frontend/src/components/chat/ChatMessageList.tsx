/*
 * 역할: 채팅 메시지 배열을 시간순으로 렌더링한다.
 * 입력: ChatMessage 배열, 디버그 노출 여부, 추천 관련 콜백.
 * 출력: 사용자/assistant/디버그/추천 결과 메시지 UI.
 * 호출 시점: ChatPage가 대화 본문을 그릴 때 호출된다.
 * TODO: 메시지 타입이 늘어나면 타입별 렌더러를 별도 파일로 분리한다.
 */

import type { ChatMessage, InterpretedConditions } from "../../types";
import { ConditionDebugMessage } from "./ConditionDebugMessage";
import { RecommendationResultMessage } from "./RecommendationResultMessage";

interface ChatMessageListProps {
  messages: ChatMessage[];
  showDebug: boolean;
  isLoading: boolean;
  onConfirmDebug: (conditions: InterpretedConditions) => void;
  onRequestMore: () => void;
  onRelaxRadius: () => void;
}

export function ChatMessageList({
  messages,
  showDebug,
  isLoading,
  onConfirmDebug,
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
              <p
                key={message.id}
                className="mr-auto max-w-xl rounded-md bg-gray-100 px-4 py-3 text-sm text-gray-800 dark:bg-gray-800 dark:text-gray-100"
              >
                {message.text}
              </p>
            );
          }

          if (message.type === "condition_debug") {
            return (
              <ConditionDebugMessage
                key={message.id}
                userInput={message.userInput}
                conditions={message.conditions}
                status={message.status}
                isLoading={isLoading}
                onConfirm={() => onConfirmDebug(message.conditions)}
              />
            );
          }

          return (
            <RecommendationResultMessage
              key={message.id}
              recommendations={message.recommendations}
              unverifiedRecommendations={message.unverified_recommendations}
              isLoading={isLoading}
              onRequestMore={onRequestMore}
              onRelaxRadius={onRelaxRadius}
            />
          );
        })}
    </div>
  );
}
