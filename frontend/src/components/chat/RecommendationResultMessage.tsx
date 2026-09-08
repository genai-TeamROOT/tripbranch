/*
 * 역할: 추천 API 응답을 채팅 메시지 안에서 장소 카드 목록으로 렌더링한다.
 * 입력: 정상 추천 목록, 운영시간 미확인 목록, 추가 추천 요청 콜백.
 * 출력: 추천 결과 메시지와 PlaceCard 목록 — **줄은 최대 두 개다**(추천 장소 /
 *   현재 운영시간이 아닌 장소). 운영시간 원문조차 없는 후보는 추천 장소 줄에
 *   함께 들어간다(2026-09-08, 아래 rankedRecommendations 주석).
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
        }
      : {
          summary: "조건에 맞춰 이런 장소를 찾아봤어요.",
          noResults: "조건에 맞는 장소를 찾지 못했어요.",
          recommendations: "추천 장소",
          closed: "현재 운영시간이 아닌 장소",
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
  /*
   * **운영시간을 모르는 후보를 추천 장소와 같은 줄에 둔다**(2026-09-08). 전에는
   * "운영시간을 확인할 수 없는 장소"라는 캡션을 달아 아래에 따로 한 줄을 더
   * 그렸다. 캡션이 없어도 그 사실은 카드가 이미 말한다 — 운영시간 자리에
   * "확인 불가"가 찍힌다(PlaceCard의 hoursRemainingLabel).
   *
   * 폐점 후보(closedRecommendations)는 계속 따로 둔다. 그 분리는 mintee가
   * 4cab841a에서 "폐점 후보의 실제 운영시간을 보존"하려고 만든 것이고, 이 변경은
   * 거기를 건드리지 않는다.
   *
   * **순위 번호가 이어 붙는다**(사용자 결정). 그래서 검증된 후보가 5개면 이 후보는
   * 6·7위로 보인다. D의 순위는 "날씨·운영시간·거리 조건을 종합한" 것이라 운영시간을
   * 모르는 후보는 그 기준으로 줄 세운 것이 아닌데도 같은 번호 체계에 들어간다는
   * 뜻이다. 검증된 후보가 하나도 없으면 이 후보가 1위 자리에 온다.
   */
  const rankedRecommendations = [...recommendations, ...unknownHoursRecommendations];
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
          {rankedRecommendations.length > 0 && (
            <PlaceCardRow caption={text.recommendations}>
              {rankedRecommendations.map((item, index) => (
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
