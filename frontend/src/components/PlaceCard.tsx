/*
 * 역할: 추천 장소 하나를 카드 형태로 렌더링한다.
 * 입력: RecommendationItem 데이터.
 * 출력: 장소명, 카테고리, 추천 이유, 주소, 검증 상태 UI.
 * 호출 시점: RecommendationResultMessage가 추천 목록과 검증 불가 목록을 표시할 때 호출된다.
 * TODO: 지도 링크, 저장/제외 액션, 실시간 영업 정보가 생기면 하위 UI를 확장한다.
 */

import type { Language, RecommendationItem } from "../types";
import { travelLabel, travelValue } from "../utils/travelDisplay";

interface PlaceCardProps {
  item: RecommendationItem;
  /** 추천 결과의 현재 정보만으로 여는 1차 상세 미리보기. */
  onOpenDetail?: (item: RecommendationItem) => void;
  language?: Language;
}

function formatRemainingDuration(remainingMinutes: number, language: Language): string {
  // 카드에서는 분 단위 정밀도보다 빠른 비교가 중요하므로, 가장 가까운 시간으로
  // 반올림한다. 운영 종료가 임박한 경우 0시간으로 보이지 않도록 최소 1시간이다.
  const hours = Math.max(1, Math.round(remainingMinutes / 60));
  return language === "en" ? `${hours} hr remaining` : `${hours}시간 남음`;
}

function formatClosingTime(remainingMinutes: number, language: Language): string {
  const closesAt = new Date(Date.now() + remainingMinutes * 60 * 1000);
  const time = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(closesAt);
  return language === "en"
    ? `Closes at ${time} (${formatRemainingDuration(remainingMinutes, language)})`
    : `운영 종료 예정 ${time} (${formatRemainingDuration(remainingMinutes, language)})`;
}

function isAlwaysOpen(operatingHours: string): boolean {
  const normalized = operatingHours.replaceAll(/\s/g, "").toLowerCase();
  return (
    normalized.includes("24시간") ||
    normalized.includes("상시개방") ||
    normalized.includes("연중무휴") ||
    normalized === "00:00~24:00" ||
    normalized === "00:00-24:00"
  );
}

function formatOperatingHours(item: RecommendationItem, language: Language): string {
  // D가 제공하는 당일 적용 운영 구간을 우선 표시한다. 이전 응답 또는 구간을
  // 판별할 수 없는 후보는 기존의 종료 예정 시각 표기로 자연스럽게 폴백한다.
  // 운영시간 무시로 폐점 후보를 함께 보여주는 경우에도 이 값은 남아 있다. 이때
  // remaining_minutes만 null이라는 이유로 "확인 불가"로 덮어쓰면 실제 운영시간을
  // 알고도 숨기게 되므로, 구간과 현재 폐점 상태를 함께 표시한다.
  if (item.operating_hours_display) {
    if (isAlwaysOpen(item.operating_hours_display)) {
      return item.operating_hours_display;
    }
    if (item.remaining_minutes === null) {
      return `${item.operating_hours_display} (${language === "en" ? "Currently closed" : "현재 운영시간 아님"})`;
    }
    return `${item.operating_hours_display} (${formatRemainingDuration(item.remaining_minutes, language)})`;
  }

  if (item.remaining_minutes === null) {
    return language === "en" ? "Unavailable" : "확인 불가";
  }

  return formatClosingTime(item.remaining_minutes, language);
}

/**
 * D의 기본 추천 사유는 구조화된 순위 문장이다. 영어 화면에서 번역 API 응답이
 * 지연되거나 구버전 응답이 섞여도, 이 고정 형식만큼은 즉시 자연스럽게 보인다.
 */
function displayRecommendationReason(reason: string, language: Language): string {
  if (language !== "en") return reason;
  const matched = reason.match(/^날씨·운영시간·거리 조건을 종합한 (\d+)순위 추천이에요\.?$/);
  if (matched) return `Recommended #${matched[1]} based on weather, opening hours, and distance.`;
  return reason;
}

export function PlaceCard({ item, onOpenDetail, language = "ko" }: PlaceCardProps) {
  const content = (
    <>
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">{item.name}</h3>
        <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-300">
          {item.category}
        </span>
      </div>

      <p className="text-sm text-gray-600 dark:text-gray-400">
        {displayRecommendationReason(item.recommendation_reason, language)}
      </p>

      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-700 dark:text-gray-300">
        <div className="flex gap-1">
          <dt className="text-gray-400">{travelLabel(item, language)}</dt>
          <dd>{travelValue(item, language)}</dd>
        </div>
        <div className="flex gap-1">
          <dt className="text-gray-400">{language === "en" ? "Opening hours" : "운영시간"}</dt>
          <dd>{formatOperatingHours(item, language)}</dd>
        </div>
      </dl>

      {item.warnings.length > 0 && (
        <ul className="flex flex-col gap-1">
          {item.warnings.map((warning) => (
            <li
              key={warning}
              className="w-fit rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
            >
              {warning}
            </li>
          ))}
        </ul>
      )}

      {onOpenDetail && (
        <span className="w-fit text-xs font-medium text-blue-700 dark:text-blue-300">
          {language === "en" ? "View place details →" : "장소 정보 미리 보기 →"}
        </span>
      )}
    </>
  );

  return (
    <li
      className={`flex flex-col gap-2 rounded-lg border border-gray-200 p-4 shadow-sm dark:border-gray-700${
        onOpenDetail
          ? " cursor-pointer text-left transition hover:border-blue-300 hover:bg-blue-50/30 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:hover:border-blue-700 dark:hover:bg-blue-950/20"
          : ""
      }`}
      role={onOpenDetail ? "button" : undefined}
      tabIndex={onOpenDetail ? 0 : undefined}
      aria-label={
        onOpenDetail
          ? language === "en"
            ? `View details for ${item.name}`
            : `${item.name} 장소 정보 미리 보기`
          : undefined
      }
      onClick={onOpenDetail ? () => onOpenDetail(item) : undefined}
      onKeyDown={
        onOpenDetail
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onOpenDetail(item);
              }
            }
          : undefined
      }
    >
      {content}
    </li>
  );
}
