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

import { useEffect, useState, type ReactNode } from "react";
import type { AgentProgressEvent, ChatMessage, Language, TravelOriginToggle } from "../../types";
import { AgentProgressMessage } from "./AgentProgressMessage";
import { ClarificationMessage } from "./ClarificationMessage";
import { CompareResultCards } from "./CompareResultCards";
import { LocationRefreshMessage } from "./LocationRefreshMessage";
import { ConditionDebugMessage } from "./ConditionDebugMessage";
import { FeedbackButtons } from "./FeedbackButtons";
import { PlaceInfoCard } from "./PlaceInfoCard";
import { PhotoSimilarResultMessage } from "./PhotoSimilarResultMessage";
import { PastRecommendationMessage } from "./PastRecommendationMessage";
import { RecommendationResultMessage } from "./RecommendationResultMessage";
import { ScheduleResultMessage } from "./ScheduleResultMessage";
import { SessionStatusMessage } from "./SessionStatusMessage";
import { SuggestedFollowUps } from "./SuggestedFollowUps";
import { findTurnText } from "../../utils/turnText";

function StreamingDots({ language }: { language: Language }) {
  const loadingLabel = language === "en" ? "Generating a response" : "답변 생성 중";
  return (
    <span className="flex h-6 items-center gap-1.5" aria-label={loadingLabel} role="status">
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          aria-hidden="true"
          className="h-2 w-2 animate-bounce rounded-full bg-brand/60"
          style={{ animationDelay: `${index * 150}ms`, animationDuration: "900ms" }}
        />
      ))}
      <span className="sr-only">{loadingLabel}</span>
    </span>
  );
}

// 줄 안의 인라인 마크다운. 지금은 **강조**만 처리한다 — 백엔드 답변 생성
// 프롬프트가 실제로 쓰는 문법이 이것뿐이라, 더 넓은 문법(링크·이탤릭 등)은
// 필요해지면 그때 추가한다.
function renderInline(text: string): ReactNode {
  const segments = text.split(/(\*\*[^*]+\*\*)/g).filter((segment) => segment !== "");
  return segments.map((segment, index) =>
    segment.startsWith("**") && segment.endsWith("**") ? (
      <strong key={index}>{segment.slice(2, -2)}</strong>
    ) : (
      <span key={index}>{segment}</span>
    ),
  );
}

// "- "/"* "/"• " 셋 다 불릿으로 본다 — 같은 답변 안에서도 모델이 섞어 쓴다.
const BULLET_PREFIXES = ["- ", "* ", "• "];

// "#"/"##"/"###"... 몇 개든 제목으로 본다 — 모델이 h1~h3를 섞어 쓴다. 1~2단계는
// 크게, 3단계부터는 한 크기로 묶는다(더 잘게 나눠봐야 챗 버블 안에서 구분이 안 감).
const HEADING_PATTERN = /^(#{1,6})\s+(.*)$/;

function MarkdownText({ text }: { text: string }) {
  const lines = text.split("\n");
  const elements: ReactNode[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    // 불릿 기호만 있고 내용은 다음 줄에 오는 경우(모델이 가끔 이렇게 끊어 보냄) —
    // 빈 불릿을 그리지 않고 건너뛴다.
    if (!line || line.trim() === "•" || line.trim() === "*") continue;
    const headingMatch = HEADING_PATTERN.exec(line);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const content = renderInline(headingMatch[2]);
      elements.push(
        level === 1 ? (
          <h2 key={`heading-${index}`} className="text-xl font-bold text-ink">
            {content}
          </h2>
        ) : (
          <h3 key={`heading-${index}`} className="mt-3 text-lg font-bold text-ink">
            {content}
          </h3>
        ),
      );
      continue;
    }
    const bulletPrefix = BULLET_PREFIXES.find((prefix) => line.startsWith(prefix));
    if (bulletPrefix) {
      elements.push(
        <p key={`item-${index}`} className="flex gap-2 text-sm">
          <span aria-hidden="true">•</span>
          <span>{renderInline(line.slice(bulletPrefix.length))}</span>
        </p>,
      );
      continue;
    }
    elements.push(
      <p key={`paragraph-${index}`} className="leading-relaxed text-ink">
        {renderInline(line)}
      </p>,
    );
  }

  return <div className="space-y-1.5">{elements}</div>;
}

function StreamingText({
  text,
  streaming,
  language,
}: {
  text: string;
  streaming: boolean;
  language: Language;
}) {
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
  return <MarkdownText text={displayText} />;
}

interface ChatMessageListProps {
  messages: ChatMessage[];
  showDebug: boolean;
  isLoading: boolean;
  deviceLocation: string | null;
  isDeveloperView?: boolean;
  onRequestMore: () => void;
  onRelaxRadius: () => void;
  onSelectClarificationOption: (optionId: string, label: string) => void;
  onSelectFollowUpSuggestion: (suggestion: string) => void;
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
  deviceLocation,
  isDeveloperView = false,
  onRequestMore,
  onRelaxRadius,
  onSelectClarificationOption,
  onSelectFollowUpSuggestion,
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
              <div key={message.id} className="flex justify-end">
                <p className="max-w-[80%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-sm text-white">
                  {message.text}
                </p>
              </div>
            );
          }

          if (message.type === "assistant_text" || message.type === "interpretation_summary") {
            return (
              // 배경·패딩 없이 본문처럼 넓게 흐른다(DESIGN_SYSTEM.md §6.3) —
              // 카드가 뒤따라 붙는 구조라 말풍선을 쓰지 않는다.
              <div key={message.id} className="flex w-full flex-col gap-2 text-sm text-ink">
                {isDeveloperView && message.type === "assistant_text" && message.intent && (
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-ink px-2 py-0.5 font-semibold text-white">
                      Intent: {message.intent}
                    </span>
                    {message.status && (
                      <span className="rounded-full border border-border px-2 py-0.5 text-muted">
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
                {message.type === "assistant_text" && message.footnote && (
                  <p className="text-xs text-muted">{message.footnote}</p>
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
              <div key={message.id} className="mr-auto flex w-full px-1">
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

          if (message.type === "follow_up_suggestions") {
            return (
              <SuggestedFollowUps
                key={message.id}
                suggestions={message.suggestions}
                isLoading={isLoading}
                onSelect={onSelectFollowUpSuggestion}
                language={language}
              />
            );
          }

          if (message.type === "photo_similar_result") {
            return (
              <PhotoSimilarResultMessage
                key={message.id}
                imageUrl={message.imageUrl}
                status={message.status}
                centerName={message.centerName}
                places={message.places}
                candidateCount={message.candidateCount}
              />
            );
          }

          if (message.type === "past_recommendation_result") {
            return (
              <PastRecommendationMessage
                key={message.id}
                places={message.places}
                language={language}
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
          schedulePlanning={progress?.stage === "scheduling"}
          progress={progress}
          language={language}
        />
      )}
    </div>
  );
}
