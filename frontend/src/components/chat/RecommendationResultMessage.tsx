/*
 * 역할: 추천 API 응답을 채팅 메시지 안에서 장소 카드 목록으로 렌더링한다.
 * 입력: 정상 추천 목록, 운영시간 미확인 목록, 추가 추천 요청 콜백.
 * 출력: 추천 결과 메시지와 PlaceCard 목록.
 *
 * **동작 버튼과 취향 표는 여기 없다.** 각각 RecommendationActionsMessage와
 * PreferenceTagSummaryTable이 별도 메시지로 그린다 — 버튼은 다음 발화가 나가면
 * 걷어내야 하는데 카드와 한 메시지에 있으면 같이 지워지기 때문이다.
 * 호출 시점: ChatPage가 recommendation_result 메시지를 렌더링할 때 호출된다.
 * 담기/빼기는 useSavedPlaces()로 직접 읽고 쓴다 — 카드가 메시지 목록 깊숙이
 * 있어 prop으로 내리면 중간 컴포넌트 셋을 전부 거쳐야 한다.
 * TODO: 지도/동선 액션이 생기면 PlaceCard 주변 액션으로 확장한다.
 *
 * showElapsedTime이 false면(실사용자 화면) 지연시간(elapsedMs/serverElapsedMs)을
 * 아예 렌더링하지 않는다 — 개발자 확인용 숫자가 실서비스 화면에 새던 걸 정리함.
 * /dev-chat(ChatMessageList의 isDeveloperView)에서만 true로 넘어온다.
 */

import { useState } from "react";
import type { Language, RecommendationItem } from "../../types";
import { useSavedPlaces } from "../../hooks/useSavedPlaces";
import { PlaceCard } from "../PlaceCard";
import { PlaceCardRow } from "./PlaceCardRow";
import { RecommendationDetailPreviewModal } from "./RecommendationDetailPreviewModal";

interface RecommendationResultMessageProps {
  recommendations: RecommendationItem[];
  unverifiedRecommendations: RecommendationItem[];
  elapsedMs: number;
  serverElapsedMs: number;
  showElapsedTime?: boolean;
  language?: Language;
}

function formatDuration(milliseconds: number | undefined) {
  if (typeof milliseconds !== "number" || !Number.isFinite(milliseconds)) return "-";
  return milliseconds >= 1000
    ? `${(milliseconds / 1000).toFixed(1)}초`
    : `${Math.round(milliseconds)}ms`;
}

export function RecommendationResultMessage({
  recommendations,
  unverifiedRecommendations,
  elapsedMs,
  serverElapsedMs,
  showElapsedTime = false,
  language = "ko",
}: RecommendationResultMessageProps) {
  const text =
    language === "en"
      ? {
          summary: "Here are some places that match your preferences.",
          noResults: "We couldn’t find a place that matches those conditions.",
          recommendations: "Recommended places",
          closed: "Places that are currently closed",
          hoursUnknown: "Places with unavailable opening hours",
        }
      : {
          summary: "조건에 맞춰 이런 장소를 찾아봤어요.",
          noResults: "조건에 맞는 장소를 찾지 못했어요.",
          recommendations: "추천 장소",
          closed: "현재 운영시간이 아닌 장소",
          hoursUnknown: "운영시간을 확인할 수 없는 장소",
        };
  const [selectedRecommendation, setSelectedRecommendation] = useState<RecommendationItem | null>(
    null,
  );
  const { savedPlaceIds, toggleSaved } = useSavedPlaces();
  // D는 운영시간을 무시한 재검색에서 "현재는 폐점"인 후보도 unverified 목록에
  // 담는다. 하지만 이 후보는 운영시간 원문 자체가 없는 것이 아니다. 카드에서
  // 실제 구간을 보여 줄 수 있도록, display가 있는 폐점 후보와 진짜 결측 후보를
  // 분리한다.
  const closedRecommendations = unverifiedRecommendations.filter(
    (item) => item.operating_hours_display,
  );
  const unknownHoursRecommendations = unverifiedRecommendations.filter(
    (item) => !item.operating_hours_display,
  );
  const hasNoResults =
    recommendations.length === 0 &&
    closedRecommendations.length === 0 &&
    unknownHoursRecommendations.length === 0;

  return (
    <article className="mr-auto flex w-full flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm text-ink">{text.summary}</p>
        {showElapsedTime && (
          <p className="text-xs text-muted">
            {formatDuration(elapsedMs)} 소요 (서버 {formatDuration(serverElapsedMs)})
          </p>
        )}
      </div>

      {hasNoResults ? (
        /* 버튼은 여기 없다 — RecommendationActionsMessage가 뒤이어 그린다.
           안내 문구는 그때 받은 답이라 기록으로 남긴다. */
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-ink">{text.noResults}</p>
        </div>
      ) : (
        <>
          {recommendations.length > 0 && (
            <PlaceCardRow caption={text.recommendations}>
              {recommendations.map((item, index) => (
                <PlaceCard
                  key={item.place_id}
                  item={item}
                  rank={index + 1}
                  language={language}
                  isSaved={savedPlaceIds.has(item.place_id)}
                  onToggleSave={(selectedItem) => void toggleSaved(selectedItem)}
                  onOpenDetail={(selectedItem) => setSelectedRecommendation(selectedItem)}
                />
              ))}
            </PlaceCardRow>
          )}

          {closedRecommendations.length > 0 && (
            <PlaceCardRow caption={text.closed}>
              {closedRecommendations.map((item) => (
                <PlaceCard
                  key={item.place_id}
                  item={item}
                  language={language}
                  isSaved={savedPlaceIds.has(item.place_id)}
                  onToggleSave={(selectedItem) => void toggleSaved(selectedItem)}
                  onOpenDetail={(selectedItem) => setSelectedRecommendation(selectedItem)}
                />
              ))}
            </PlaceCardRow>
          )}

          {unknownHoursRecommendations.length > 0 && (
            <PlaceCardRow caption={text.hoursUnknown}>
              {unknownHoursRecommendations.map((item) => (
                <PlaceCard
                  key={item.place_id}
                  item={item}
                  language={language}
                  isSaved={savedPlaceIds.has(item.place_id)}
                  onToggleSave={(selectedItem) => void toggleSaved(selectedItem)}
                  onOpenDetail={(selectedItem) => setSelectedRecommendation(selectedItem)}
                />
              ))}
            </PlaceCardRow>
          )}
        </>
      )}

      {selectedRecommendation && (
        <RecommendationDetailPreviewModal
          item={selectedRecommendation}
          onClose={() => setSelectedRecommendation(null)}
        />
      )}
    </article>
  );
}
