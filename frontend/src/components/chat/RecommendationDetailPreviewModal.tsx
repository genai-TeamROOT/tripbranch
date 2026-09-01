/*
 * 역할: 추천/INFO 카드 클릭 시 C PlaceDetails를 모달로 표시한다.
 * 입력: D 추천 결과(거리·운영시간) 또는 INFO가 이미 받은 InfoPlaceCard.
 * 출력: 모달의 썸네일·개요·운영·휴무·주차·요금·편의시설.
 * 호출 시점: RecommendationResultMessage의 추천 카드 클릭.
 */

import { useEffect, useState } from "react";
import { fetchRecommendationPlaceDetails } from "../../api/trip";
import { useTripState } from "../../state/TripContext";
import type { InfoPlaceCard, RecommendationItem } from "../../types";
import { openNaverDirections, openNaverMapSearch } from "../../utils/naverDirections";
import { travelLabel, travelValue } from "../../utils/travelDisplay";
import {
  ConcentrationForecastBars,
  PopulationForecastBars,
  RoadTrafficStatusSection,
} from "./CongestionForecastBars";

interface RecommendationDetailPreviewModalProps {
  /** 추천 카드에서 열면 현재 거리·운영시간과 함께 C 상세를 추가 조회한다. */
  item?: RecommendationItem;
  /** INFO 카드에서 열면 답변 요약을 즉시 표시한다. */
  card?: InfoPlaceCard;
  /**
   * 사진 검색 결과에서 열 때. 그 결과는 content_id와 유사도뿐이라 위 두 모양을
   * 만들 수 없어, 조회에 필요한 최소값만 받는다.
   */
  placeId?: string;
  placeName?: string;
  onClose: () => void;
}

/**
 * 주소·혼잡도·행사 INFO는 첫 응답에서 필요한 값만 받아온다. 카드 클릭 때만
 * 전체 PlaceDetails를 보강 조회해, 답변 단계의 불필요한 상세 API 호출은 피한다.
 */
function needsDetailEnrichment(card: InfoPlaceCard | undefined): boolean {
  // 실시간 도시데이터 INFO는 이미 지역 단위 상세·지도 링크를 응답에 실었다.
  // 관광 PlaceDetails를 다시 조회하면 이 값을 덮어써 모달의 실시간 근거가 사라진다.
  if (card?.realtime_map_url || (card?.realtime_detail_items?.length ?? 0) > 0) return false;
  return Boolean(card && ["location_info", "concentration", "event"].includes(card.question_type));
}

function formatOperatingHours(item: RecommendationItem): string {
  if (item.operating_hours_display) {
    return item.remaining_minutes === null
      ? `${item.operating_hours_display} (현재 운영시간 아님)`
      : item.operating_hours_display;
  }
  return "확인 불가";
}

const DETAIL_FIELDS: Array<[keyof InfoPlaceCard, string]> = [
  ["operating_hours", "운영시간"],
  ["rest_date", "휴무일"],
  ["parking", "주차"],
  ["parking_fee", "주차 요금"],
  ["fee", "요금"],
];

const FACILITY_FIELDS: Array<[keyof InfoPlaceCard, string]> = [
  ["baby_carriage", "유모차"],
  ["pet", "반려동물 동반"],
  ["credit_card", "카드 결제"],
  ["restroom", "화장실"],
];

const SEOUL_PARKING_PORTAL_URL = "https://parking.seoul.go.kr/";

const ANSWER_FIELD_LABELS: Record<string, string> = {
  address: "주소",
  concentration: "혼잡도",
  event: "행사",
  "상권 지역": "상권 지역",
  "상권 기준": "상권 기준",
  업종: "업종",
  "실시간 활동": "실시간 활동",
  "기준 시각": "기준 시각",
  안내: "안내",
  homepage: "홈페이지",
  operating_hours: "운영시간",
  rest_date: "휴무일",
  parking: "주차",
  parking_fee: "주차 요금",
  fee: "요금",
  baby_carriage: "유모차",
  pet: "반려동물 동반",
  credit_card: "카드 결제",
  restroom: "화장실",
};

function formatDetailValue(key: keyof InfoPlaceCard, value: string): string {
  let formatted = value.replace(/\s*※\s*/g, "\n※ ");
  if (key === "fee") formatted = formatted.replace(/(?:^|\s)-\s*/g, "\n- ");
  return formatted.trim();
}

function DetailText({ fieldKey, value }: { fieldKey: keyof InfoPlaceCard; value: string }) {
  // ※로 시작하는 TourAPI 예외·보충 안내는 핵심 값과 중요도가 다르다. 모든 상세
  // 모달이 이 컴포넌트를 거치므로 추천 카드와 INFO 카드의 가독성도 함께 맞춰진다.
  const lines = formatDetailValue(fieldKey, value).split("\n");
  return (
    <dd className="mt-1 space-y-1">
      {lines.map((line, index) =>
        line.startsWith("※") ? (
          <p
            key={`${line}-${index}`}
            className="pt-1 text-xs leading-5 text-gray-500 dark:text-gray-400"
          >
            {line}
          </p>
        ) : (
          <p
            key={`${line}-${index}`}
            className="whitespace-pre-line text-gray-900 dark:text-gray-100"
          >
            {line}
          </p>
        ),
      )}
    </dd>
  );
}

interface OperatingHoursRow {
  period: string;
  hours: string;
}

function parseOperatingHours(value: string): OperatingHoursRow[] | null {
  // TourAPI 원문은 "[기간]시간[기간]시간"처럼 구분자 없이 이어지는 경우가 있다.
  const rows = Array.from(value.matchAll(/\[([^\]]+)\]\s*-?\s*(.*?)(?=\[|$)/g))
    .map(([, period, hours]) => ({
      period: period.trim().split("/").join(" · "),
      hours: hours
        .trim()
        .replace(/(\d{2}:\d{2})\s*~\s*(\d{2}:\d{2})/g, "$1–$2")
        .replace(/\(\s*입장\s*마감\s*([^)]+)\)/g, "· 입장 마감 $1")
        .replace(/\s{2,}/g, " "),
    }))
    .filter(({ period, hours }) => period && hours);
  return rows.length > 0 ? rows : null;
}

function OperatingHoursRows({ rows }: { rows: OperatingHoursRow[] }) {
  return (
    <div className="mt-2 grid gap-2 sm:grid-cols-2">
      {rows.map(({ period, hours }) => (
        <div
          key={period}
          className="rounded border border-gray-200 bg-white px-3 py-2 dark:border-gray-700 dark:bg-gray-900"
        >
          <p className="text-xs font-semibold text-gray-700 dark:text-gray-200">{period}</p>
          <p className="mt-0.5 text-sm text-gray-900 dark:text-gray-100">{hours}</p>
        </div>
      ))}
    </div>
  );
}

function DetailEntries({
  card,
  entries,
}: {
  card: InfoPlaceCard;
  entries: Array<[keyof InfoPlaceCard, string]>;
}) {
  const visibleEntries = entries.filter(([key]) => {
    const value = card[key];
    return typeof value === "string" && value.trim();
  });
  if (visibleEntries.length === 0) return null;

  return (
    <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
      {visibleEntries.map(([key, label]) => {
        const value = card[key];
        if (typeof value !== "string") return null;
        const operatingHours = key === "operating_hours" ? parseOperatingHours(value) : null;
        return (
          <div
            key={key}
            className={`rounded-lg bg-gray-50 p-3 dark:bg-gray-800/70${
              operatingHours ? " sm:col-span-2" : ""
            }`}
          >
            <dt className="text-xs text-gray-500 dark:text-gray-400">{label}</dt>
            {operatingHours ? (
              <dd>
                <OperatingHoursRows rows={operatingHours} />
              </dd>
            ) : (
              <DetailText fieldKey={key} value={value} />
            )}
          </div>
        );
      })}
    </dl>
  );
}

function sourceLabel(sourceType: string): string {
  if (sourceType === "google_review") return "Google 리뷰";
  if (sourceType === "naver_post") return "네이버 블로그";
  if (sourceType === "tour_overview") return "관광공사 장소 정보";
  return "방문자 후기";
}

function PreferenceInsightsSection({ card }: { card: InfoPlaceCard }) {
  const insights = card.preference_insights ?? [];
  if (insights.length === 0) return null;

  return (
    <section className="rounded-xl border border-blue-100 bg-blue-50/50 p-4 dark:border-blue-950/70 dark:bg-blue-950/20">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            방문자 후기에 나타난 특징
          </h3>
          <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-300">
            같은 문서에서 반복된 표현은 한 번만 집계했어요.
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {insights.map((insight, index) => {
          return (
            <details
              key={insight.code}
              open={index === 0}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2 dark:border-gray-700 dark:bg-gray-900"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                <p className="min-w-0 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {insight.label}
                  <span className="ml-2 text-xs font-medium text-blue-600 dark:text-blue-300">
                    {insight.mention_count}개 후기
                  </span>
                </p>
              </summary>

              <div className="mt-2 space-y-3 border-t border-gray-100 pt-2.5 dark:border-gray-800">
                {insight.evidence.map((evidence, evidenceIndex) => (
                  <blockquote
                    key={`${evidence.text}-${evidenceIndex}`}
                    className="border-l-2 border-blue-300 pl-3 text-sm leading-6 text-gray-700 dark:text-gray-300"
                  >
                    <p>“{evidence.text}”</p>
                    <EvidenceSource evidence={evidence} />
                  </blockquote>
                ))}
                {insight.evidence.length === 0 && (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    대표 문장을 준비하고 있어요.
                  </p>
                )}
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

function EvidenceSource({
  evidence,
}: {
  evidence: NonNullable<InfoPlaceCard["preference_insights"]>[number]["evidence"][number];
}) {
  const label = sourceLabel(evidence.source_type);
  return evidence.source_url ? (
    <a
      href={evidence.source_url}
      target="_blank"
      rel="noreferrer"
      className="mt-1 inline-block text-xs font-medium text-blue-700 hover:underline dark:text-blue-300"
    >
      {label} ↗
    </a>
  ) : (
    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{label}</p>
  );
}

// www.로 시작하는 프로토콜 없는 도메인도 잡는다(실측: TourAPI homepage 필드의
// 3.6%가 이 형태 — "www.kh.or.kr"처럼 http(s):// 없이 온다). 일반 도메인 정규식은
// 숫자·단위 표기(예: "3.5km")를 오탐할 수 있어 www. 접두만 좁게 잡는다.
const URL_PATTERN = /(https?:\/\/[^\s]+|www\.[^\s]+)/g;

function isLinkable(part: string): boolean {
  return /^(https?:\/\/|www\.)/.test(part);
}

function toHref(part: string): string {
  // www.만 있으면 상대경로로 오인돼 우리 사이트 안의 없는 페이지로 이동한다.
  return part.startsWith("www.") ? `https://${part}` : part;
}

/** "관련 정보" 값 안의 URL(http(s) 또는 www.)을 클릭 가능한 링크로 만든다. */
function AnswerValue({ value }: { value: string }) {
  const parts = value.split(URL_PATTERN);
  return (
    <dd className="whitespace-pre-line text-gray-900 dark:text-gray-100">
      {parts.map((part, index) =>
        isLinkable(part) ? (
          <a
            key={index}
            href={toHref(part)}
            target="_blank"
            rel="noreferrer"
            className="break-all text-blue-600 underline hover:text-blue-700 dark:text-blue-400"
          >
            {part}
          </a>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </dd>
  );
}

type RealtimeDetailItem = NonNullable<InfoPlaceCard["realtime_detail_items"]>[number];
type ParkingTab = "전체" | "공영" | "민영" | "기타";

interface ParkingCardItem {
  item: RealtimeDetailItem;
  category: Exclude<ParkingTab, "전체">;
  availableSpaces: number | null;
  capacity: number | null;
  currentParkedCount: number | null;
}

function isRealtimeParkingCard(card: InfoPlaceCard): boolean {
  return ["realtime_parking", "realtime_public_parking"].includes(card.question_type);
}

function extractParkingCount(value: string | undefined): number | null {
  const matched = value?.match(/\d[\d,]*/);
  return matched ? Number(matched[0].replaceAll(",", "")) : null;
}

function extractParkingCountFromSubtitle(
  subtitle: string | null | undefined,
  labels: string[],
): number | null {
  if (!subtitle) return null;
  for (const label of labels) {
    const matched = subtitle.match(new RegExp(`${label}\\s*([\\d,]+)\\s*(?:대|면)?`));
    if (matched) return Number(matched[1].replaceAll(",", ""));
  }
  return null;
}

function toParkingCardItem(item: RealtimeDetailItem, questionType: string): ParkingCardItem {
  const type = item.details["유형"];
  const category: Exclude<ParkingTab, "전체"> =
    type === "공영" || type === "민영"
      ? type
      : questionType === "realtime_public_parking"
        ? "공영"
        : "기타";
  return {
    item,
    category,
    // 배포 중 백엔드 재시작 전에도 기존 키(잔여 면수/총 주차면)를 읽는다.
    availableSpaces:
      extractParkingCount(item.details["가능 주차"] ?? item.details["잔여 면수"]) ??
      extractParkingCountFromSubtitle(item.subtitle, ["잔여", "가능"]),
    capacity:
      extractParkingCount(item.details["총 주차"] ?? item.details["총 주차면"]) ??
      extractParkingCountFromSubtitle(item.subtitle, ["총"]),
    currentParkedCount:
      extractParkingCount(item.details["현재 주차"]) ??
      extractParkingCountFromSubtitle(item.subtitle, ["현재"]),
  };
}

function formatParkingCount(value: number | null): string {
  return value === null ? "정보 미제공" : `${new Intl.NumberFormat("ko-KR").format(value)}대`;
}

function parkingStatus(item: ParkingCardItem): "여유" | "보통" | "혼잡" | "현황 미제공" {
  if (item.availableSpaces === null || item.capacity === null || item.capacity === 0)
    return "현황 미제공";
  const availableRatio = item.availableSpaces / item.capacity;
  if (availableRatio >= 0.4) return "여유";
  if (availableRatio >= 0.15) return "보통";
  return "혼잡";
}

function parkingStatusClass(status: ReturnType<typeof parkingStatus>): string {
  if (status === "여유")
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300";
  if (status === "보통")
    return "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300";
  if (status === "혼잡") return "bg-rose-100 text-rose-800 dark:bg-rose-950/50 dark:text-rose-300";
  return "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300";
}

function ParkingLotCard({ parkingItem }: { parkingItem: ParkingCardItem }) {
  const { item, availableSpaces, capacity, currentParkedCount } = parkingItem;
  const status = parkingStatus(parkingItem);
  const address = item.details["주소"];

  return (
    <article className="rounded-xl border border-gray-100 bg-white p-3 shadow-sm dark:border-gray-800 dark:bg-gray-900">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <span className="inline-flex rounded-md bg-sky-100 px-1.5 py-0.5 text-[11px] font-semibold text-sky-800 dark:bg-sky-950/50 dark:text-sky-300">
            {parkingItem.category}
          </span>
          <h4 className="mt-1 break-keep text-sm font-semibold leading-5 text-gray-900 dark:text-gray-100">
            {item.title}
          </h4>
          <p
            className="mt-1 truncate text-xs text-gray-500 dark:text-gray-400"
            title={address ?? item.details["거리"] ?? undefined}
          >
            {address ?? item.details["거리"] ?? "주소 정보 미제공"}
          </p>
        </div>
        <span
          className={`shrink-0 whitespace-nowrap rounded-full px-2 py-1 text-xs font-semibold ${parkingStatusClass(status)}`}
        >
          {status}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="min-w-0 rounded-lg bg-sky-50 px-2.5 py-2 dark:bg-sky-950/30">
          <p className="whitespace-nowrap text-[11px] text-sky-700 dark:text-sky-300">가능 주차</p>
          <p className="mt-0.5 text-sm font-bold leading-5 text-gray-900 dark:text-gray-100">
            {availableSpaces === null
              ? "잔여 정보 미제공"
              : `${new Intl.NumberFormat("ko-KR").format(availableSpaces)}대 가능`}
          </p>
        </div>
        <div className="min-w-0 rounded-lg bg-gray-50 px-2.5 py-2 dark:bg-gray-800">
          <p className="whitespace-nowrap text-[11px] text-gray-500 dark:text-gray-400">
            주차 규모
          </p>
          <p className="mt-0.5 text-sm font-bold leading-5 text-gray-900 dark:text-gray-100">
            {capacity === null
              ? "총 대수 미제공"
              : `총 ${new Intl.NumberFormat("ko-KR").format(capacity)}대`}
          </p>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-gray-600 dark:text-gray-300">
        {currentParkedCount !== null && (
          <span className="whitespace-nowrap rounded-full bg-gray-100 px-2 py-1 dark:bg-gray-800">
            {new Intl.NumberFormat("ko-KR").format(currentParkedCount)}대 주차 중
          </span>
        )}
        {item.details["거리"] && (
          <span className="whitespace-nowrap rounded-full bg-gray-100 px-2 py-1 dark:bg-gray-800">
            {item.details["거리"]}
          </span>
        )}
        {item.details["요금"] && (
          <span className="whitespace-nowrap rounded-full bg-gray-100 px-2 py-1 dark:bg-gray-800">
            {item.details["요금"]}
          </span>
        )}
      </div>
      {item.details["기준 시각"] && (
        <p className="mt-2 text-[11px] text-gray-400 dark:text-gray-500">
          {item.details["기준 시각"]} 기준
        </p>
      )}
      {address && (
        <button
          type="button"
          onClick={() => openNaverMapSearch(address, item.title)}
          className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 transition-colors hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-300 dark:hover:bg-blue-950/60"
        >
          <span aria-hidden="true">🧭</span>
          네이버 지도로 길찾기
        </button>
      )}
    </article>
  );
}

function RealtimeDetailLinks({ card }: { card: InfoPlaceCard }) {
  return (
    <div className="flex flex-wrap gap-2">
      {card.realtime_source_url && (
        <a
          href={card.realtime_source_url}
          target="_blank"
          rel="noreferrer"
          className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:border-sky-800 dark:bg-gray-900 dark:text-sky-300 dark:hover:bg-sky-900/50"
        >
          서울시 데이터 출처 ↗
        </a>
      )}
      {isRealtimeParkingCard(card) && (
        <a
          href={SEOUL_PARKING_PORTAL_URL}
          target="_blank"
          rel="noreferrer"
          className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:border-sky-800 dark:bg-gray-900 dark:text-sky-300 dark:hover:bg-sky-900/50"
        >
          서울시 실시간 주차정보 ↗
        </a>
      )}
      {card.realtime_map_url && (
        <a
          href={card.realtime_map_url}
          target="_blank"
          rel="noreferrer"
          className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:border-sky-800 dark:bg-gray-900 dark:text-sky-300 dark:hover:bg-sky-900/50"
        >
          실시간 혼잡도 지도 ↗
        </a>
      )}
    </div>
  );
}

function RealtimeParkingEntries({ card }: { card: InfoPlaceCard }) {
  const items = (card.realtime_detail_items ?? []).map((item) =>
    toParkingCardItem(item, card.question_type),
  );
  const [activeTab, setActiveTab] = useState<ParkingTab>("전체");
  const tabs: ParkingTab[] = ["전체", "공영", "민영", "기타"];
  const tabCounts = Object.fromEntries(
    tabs.map((tab) => [
      tab,
      tab === "전체" ? items.length : items.filter((item) => item.category === tab).length,
    ]),
  ) as Record<ParkingTab, number>;
  const visibleItems = items.filter((item) => activeTab === "전체" || item.category === activeTab);
  const visibleRealtimeItems = visibleItems.filter((item) => item.availableSpaces !== null);
  const visibleUnavailableItems = visibleItems.filter((item) => item.availableSpaces === null);
  const realtimeItems = items.filter((item) => item.availableSpaces !== null);
  const totalAvailable = realtimeItems.reduce((sum, item) => sum + (item.availableSpaces ?? 0), 0);
  const totalCapacity = items.reduce((sum, item) => sum + (item.capacity ?? 0), 0);

  return (
    <section className="rounded-2xl border border-sky-100 bg-gradient-to-b from-sky-50 to-white p-4 shadow-sm dark:border-sky-900/60 dark:from-sky-950/30 dark:to-gray-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-wide text-sky-700 dark:text-sky-300">
            REALTIME PARKING
          </p>
          <h3 className="mt-0.5 text-lg font-bold text-gray-900 dark:text-gray-100">주차장 현황</h3>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
            {card.realtime_area_name ?? "가까운 서울시 제공 지역"}
            {card.realtime_observed_at ? ` · ${card.realtime_observed_at} 기준` : ""}
          </p>
        </div>
        <RealtimeDetailLinks card={card} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-blue-600 px-3 py-3 text-white shadow-sm">
          <p className="whitespace-nowrap text-xs font-medium text-blue-100">현재 가능한 주차</p>
          <p className="mt-1 whitespace-nowrap text-xl font-bold">
            {realtimeItems.length > 0
              ? `${new Intl.NumberFormat("ko-KR").format(totalAvailable)}대`
              : "정보 없음"}
          </p>
        </div>
        <div className="rounded-xl border border-sky-100 bg-white px-3 py-3 dark:border-sky-900/60 dark:bg-gray-900">
          <p className="whitespace-nowrap text-xs text-gray-500 dark:text-gray-400">실시간 제공</p>
          <p className="mt-1 whitespace-nowrap text-xl font-bold text-gray-900 dark:text-gray-100">
            {realtimeItems.length}곳
          </p>
        </div>
        <div className="rounded-xl border border-sky-100 bg-white px-3 py-3 dark:border-sky-900/60 dark:bg-gray-900">
          <p className="whitespace-nowrap text-xs text-gray-500 dark:text-gray-400">공영 주차장</p>
          <p className="mt-1 whitespace-nowrap text-xl font-bold text-gray-900 dark:text-gray-100">
            {tabCounts["공영"]}곳
          </p>
        </div>
        <div className="rounded-xl border border-sky-100 bg-white px-3 py-3 dark:border-sky-900/60 dark:bg-gray-900">
          <p className="whitespace-nowrap text-xs text-gray-500 dark:text-gray-400">목록 총 수용</p>
          <p className="mt-1 whitespace-nowrap text-xl font-bold text-gray-900 dark:text-gray-100">
            {formatParkingCount(totalCapacity)}
          </p>
        </div>
      </div>

      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        가능한 주차 대수는 실시간 정보가 제공된 주차장만 합산합니다.
      </p>

      <div className="mt-4 grid grid-cols-4 rounded-xl border border-sky-100 bg-white p-1 dark:border-sky-900/60 dark:bg-gray-900">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            disabled={tabCounts[tab] === 0}
            aria-pressed={activeTab === tab}
            className={`rounded-lg px-2 py-2 text-xs font-semibold transition sm:text-sm ${
              activeTab === tab
                ? "bg-blue-600 text-white shadow-sm"
                : "text-gray-500 hover:bg-sky-50 disabled:cursor-not-allowed disabled:text-gray-300 dark:text-gray-400 dark:hover:bg-sky-950/30"
            }`}
          >
            {tab} {tabCounts[tab]}
          </button>
        ))}
      </div>

      <div className="mt-3 space-y-3">
        {visibleRealtimeItems.length > 0 && (
          <section aria-labelledby="realtime-parking-available-heading">
            <div className="mb-2 flex items-center justify-between">
              <h4
                id="realtime-parking-available-heading"
                className="text-sm font-semibold text-gray-900 dark:text-gray-100"
              >
                실시간 주차 가능
              </h4>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {visibleRealtimeItems.length}곳
              </span>
            </div>
            <div className="space-y-2">
              {visibleRealtimeItems.map((parkingItem, index) => (
                <ParkingLotCard
                  key={`${parkingItem.item.title}-realtime-${index}`}
                  parkingItem={parkingItem}
                />
              ))}
            </div>
          </section>
        )}

        {visibleUnavailableItems.length > 0 && (
          <details
            className="rounded-xl border border-gray-200 bg-gray-50 p-2 dark:border-gray-800 dark:bg-gray-950/40"
            open={visibleRealtimeItems.length === 0}
          >
            <summary className="flex cursor-pointer list-none items-center justify-between rounded-lg px-2 py-2 text-sm font-semibold text-gray-700 hover:bg-white dark:text-gray-200 dark:hover:bg-gray-900">
              <span>실시간 잔여 현황 미제공</span>
              <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                {visibleUnavailableItems.length}곳 보기
              </span>
            </summary>
            <div className="mt-2 space-y-2">
              {visibleUnavailableItems.map((parkingItem, index) => (
                <ParkingLotCard
                  key={`${parkingItem.item.title}-unavailable-${index}`}
                  parkingItem={parkingItem}
                />
              ))}
            </div>
          </details>
        )}
        {visibleItems.length === 0 && (
          <p className="rounded-xl bg-white px-3 py-4 text-center text-sm text-gray-500 dark:bg-gray-900 dark:text-gray-400">
            이 유형의 주차장 정보는 제공되지 않습니다.
          </p>
        )}
      </div>
    </section>
  );
}

function RealtimeDetailEntries({ card }: { card: InfoPlaceCard }) {
  const items = card.realtime_detail_items ?? [];
  if (items.length === 0 && !card.realtime_map_url && !card.realtime_source_url) return null;
  if (isRealtimeParkingCard(card)) return <RealtimeParkingEntries card={card} />;

  return (
    <section className="rounded-xl border border-sky-100 bg-sky-50/70 p-4 dark:border-sky-900/60 dark:bg-sky-950/20">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            실시간 지역 정보
          </h3>
          <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-300">
            {card.realtime_area_name ?? "가까운 서울시 제공 지역"}
            {card.realtime_observed_at ? ` · ${card.realtime_observed_at} 기준` : ""}
          </p>
        </div>
        <RealtimeDetailLinks card={card} />
      </div>
      {card.realtime_map_url && (
        <iframe
          title={`${card.realtime_area_name ?? "서울시"} 실시간 혼잡도 지도`}
          src={card.realtime_map_url}
          loading="lazy"
          className="mt-3 h-[78vh] min-h-[680px] w-full rounded-lg border border-sky-100 bg-white dark:border-sky-900/60 dark:bg-gray-900"
        />
      )}
      <div className="mt-3 space-y-3">
        {items.map((item, index) => (
          <article
            key={`${item.title}-${index}`}
            className="overflow-hidden rounded-lg border border-sky-100 bg-white dark:border-sky-900/60 dark:bg-gray-900"
          >
            {item.thumbnail_url && (
              <img
                src={item.thumbnail_url}
                alt={`${item.title} 이미지`}
                loading="lazy"
                className="h-36 w-full bg-gray-100 object-cover dark:bg-gray-800"
              />
            )}
            <div className="p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {item.title}
                  </h4>
                  {item.subtitle && (
                    <p className="mt-0.5 text-sm text-sky-700 dark:text-sky-300">{item.subtitle}</p>
                  )}
                </div>
                {item.external_url && (
                  <a
                    href={item.external_url}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 text-xs font-medium text-blue-700 hover:underline dark:text-blue-300"
                  >
                    자세히 보기 ↗
                  </a>
                )}
              </div>
              {Object.keys(item.details).length > 0 && (
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                  {Object.entries(item.details).map(([key, value]) => (
                    <div key={key} className="min-w-0">
                      <dt className="text-gray-500 dark:text-gray-400">{key}</dt>
                      <dd className="mt-0.5 break-words text-gray-800 dark:text-gray-100">
                        {value}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

/**
 * 상세 모달의 사진 영역. 여러 장이면 갤러리로, 한 장이면 지금까지처럼 한 장만 그린다.
 *
 * 두 출처를 합쳐서 본다. photos는 place_image_embeddings에 적재된 detailImage2
 * 사진이고, thumbnail_url은 places 행의 대표 이미지다. 사진 목록이 있는 장소가
 * 전체의 30%뿐이라(2026-08-31 실측) 목록만 보고 그리면 나머지 장소에서 지금
 * 보이던 사진이 사라진다.
 */
function PlacePhotoGallery({ card, title }: { card: InfoPlaceCard; title: string }) {
  const photos = card.photos ?? [];
  // 목록이 비었을 때만 대표 이미지로 대체한다. 둘 다 있으면 목록이 이미 그
  // 장소의 사진들이라 대표 이미지를 덧붙이면 같은 사진이 두 번 나올 수 있다.
  const urls =
    photos.length > 0
      ? photos.map((photo) => photo.url)
      : card.thumbnail_url
        ? [card.thumbnail_url]
        : [];
  const [activeIndex, setActiveIndex] = useState(0);

  // 모달을 연 채로 다른 장소의 상세가 도착하면 선택을 처음으로 되돌린다. 안 되돌리면
  // 사진이 3장인 곳에서 3번째를 보다가 1장짜리 장소로 바뀌었을 때 빈 자리가 남는다.
  const firstUrl = urls[0];
  useEffect(() => {
    setActiveIndex(0);
  }, [firstUrl]);

  if (urls.length === 0) return null;

  const safeIndex = Math.min(activeIndex, urls.length - 1);
  const placeName = card.place_name ?? title;

  return (
    <div className="flex flex-col gap-2">
      <div className="relative">
        <img
          src={urls[safeIndex]}
          alt={
            urls.length > 1 ? `${placeName} 사진 ${safeIndex + 1}번째` : `${placeName} 이미지`
          }
          className="h-56 w-full rounded-xl bg-gray-100 object-cover dark:bg-gray-800"
        />
        {urls.length > 1 && (
          <span className="absolute bottom-2 right-2 rounded-full bg-black/60 px-2 py-0.5 text-xs font-medium text-white">
            {safeIndex + 1} / {urls.length}
          </span>
        )}
      </div>
      {urls.length > 1 && (
        <div
          className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1"
          role="group"
          aria-label={`${placeName} 사진 목록`}
        >
          {urls.map((url, index) => (
            <button
              key={`${url}-${index}`}
              type="button"
              onClick={() => setActiveIndex(index)}
              aria-label={`${placeName} 사진 ${index + 1}번째 보기`}
              aria-current={index === safeIndex}
              className={`h-14 w-14 shrink-0 overflow-hidden rounded-lg border-2 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                index === safeIndex
                  ? "border-blue-600 dark:border-blue-400"
                  : "border-transparent opacity-70 hover:opacity-100"
              }`}
            >
              <img
                src={url}
                alt=""
                loading="lazy"
                className="h-full w-full bg-gray-100 object-cover dark:bg-gray-800"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** 추천/INFO 어디서 열어도 같은 모양으로 PlaceDetails를 보여주는 상세 모달이다. */
export function RecommendationDetailPreviewModal({
  item,
  card,
  placeId: placeIdProp,
  placeName: placeNameProp,
  onClose,
}: RecommendationDetailPreviewModalProps) {
  const { device_location } = useTripState();
  const [detailCard, setDetailCard] = useState<InfoPlaceCard | null>(card ?? null);
  const [detailStatus, setDetailStatus] = useState<"loading" | "no_data" | "unavailable">(
    "loading",
  );
  const placeId = card?.place_id ?? item?.place_id ?? placeIdProp;
  const placeName = card?.place_name ?? item?.name ?? placeNameProp;
  const title =
    detailCard?.place_name ?? card?.place_name ?? item?.name ?? placeNameProp ?? "장소 상세 정보";
  const isLoading = detailStatus === "loading" && !detailCard;
  // 목적지 좌표와 현재 위치가 모두 있어야 길찾기 딥링크를 만들 수 있다.
  const canRoute =
    detailCard?.latitude != null && detailCard?.longitude != null && Boolean(device_location);
  // "관련 정보"(answer_fields)에서 개요는 아래 "개요" 섹션과 내용이 같아 제외한다(중복 제거).
  // 홈페이지는 answer_fields가 아니라 카드 최상위 필드다(질문 유형이 general_info가
  // 아니어도 백엔드가 채울 수 있다) — 하단 링크를 없앤 대신 여기서 합성해 넣는다.
  const answerEntries = detailCard && !isRealtimeParkingCard(detailCard)
    ? [
        ...Object.entries(detailCard.answer_fields).filter(([key]) => key !== "overview"),
        ...(detailCard.homepage && !("homepage" in detailCard.answer_fields)
          ? ([["homepage", detailCard.homepage]] as [string, string][])
          : []),
      ]
    : [];
  const hasRealtimeDetails =
    (detailCard?.realtime_detail_items?.length ?? 0) > 0 || Boolean(detailCard?.realtime_map_url);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    const shouldEnrichCard = needsDetailEnrichment(card);
    if (card && !shouldEnrichCard) {
      setDetailCard(card);
      return;
    }
    // 이름만 있으면 상세를 조회한다. 혼잡도·행사 카드는 place_id가 없지만
    // 이름으로 조회해 전체 상세(좌표 포함)를 받는다.
    if (!placeName) {
      setDetailStatus("no_data");
      return;
    }
    let cancelled = false;
    // INFO 답변의 요약(주소·혼잡도·행사)은 상세 조회 중에도 남겨 둔다.
    setDetailCard(card ?? null);
    setDetailStatus("loading");

    void fetchRecommendationPlaceDetails({ place_id: placeId, place_name: placeName })
      .then((response) => {
        if (cancelled) return;
        if (response.status === "success" && response.place_card) {
          setDetailCard(
            card
              ? {
                  ...response.place_card,
                  question_type: card.question_type,
                  answer_fields: card.answer_fields,
                }
              : response.place_card,
          );
          return;
        }
        setDetailStatus(response.status === "unavailable" ? "unavailable" : "no_data");
      })
      .catch(() => {
        if (!cancelled) setDetailStatus("unavailable");
      });

    return () => {
      cancelled = true;
    };
  }, [card, placeId, placeName]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end bg-black/50 p-0 sm:items-center sm:justify-center sm:p-4"
      role="presentation"
      onMouseDown={onClose}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="recommendation-detail-title"
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white shadow-xl dark:bg-gray-900 sm:rounded-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-gray-100 px-5 py-4 dark:border-gray-800">
          <div className="min-w-0">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {item ? "추천 장소 상세" : "장소 상세"}
            </p>
            <h2
              id="recommendation-detail-title"
              className="truncate text-lg font-bold text-gray-900 dark:text-gray-100"
            >
              {title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-2 text-gray-500 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:hover:bg-gray-800"
            aria-label="상세 창 닫기"
          >
            ×
          </button>
        </div>

        <div className="flex flex-col gap-5 p-5">
          {isLoading ? (
            <div className="flex h-56 animate-pulse items-center justify-center rounded-xl bg-gray-100 text-sm text-gray-500 dark:bg-gray-800 dark:text-gray-400">
              상세 정보를 불러오는 중...
            </div>
          ) : detailCard && (detailCard.photos?.length || detailCard.thumbnail_url) ? (
            <PlacePhotoGallery card={detailCard} title={title} />
          ) : !hasRealtimeDetails ? (
            <div className="flex h-56 items-center justify-center rounded-xl border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800/60 dark:text-gray-400">
              {detailStatus === "unavailable"
                ? "상세 정보를 불러오지 못했어요."
                : "등록된 이미지가 없어요."}
            </div>
          ) : null}

          {canRoute && detailCard && (
            <button
              type="button"
              onClick={() =>
                openNaverDirections({
                  deviceLocation: device_location as string,
                  destLat: detailCard.latitude as number,
                  destLng: detailCard.longitude as number,
                  destName: detailCard.place_name ?? title,
                })
              }
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <span aria-hidden="true">🧭</span>
              네이버 지도로 길찾기
            </button>
          )}

          {item && (
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg bg-gray-50 p-3 dark:bg-gray-800/70">
                <dt className="text-xs text-gray-500 dark:text-gray-400">{travelLabel(item)}</dt>
                <dd className="mt-1 font-medium text-gray-900 dark:text-gray-100">
                  {travelValue(item)}
                </dd>
              </div>
              <div className="rounded-lg bg-gray-50 p-3 dark:bg-gray-800/70">
                <dt className="text-xs text-gray-500 dark:text-gray-400">운영시간</dt>
                <dd className="mt-1 font-medium text-gray-900 dark:text-gray-100">
                  {formatOperatingHours(item)}
                </dd>
              </div>
            </dl>
          )}

          {isLoading ? (
            <div className="h-44 animate-pulse rounded-xl bg-gray-100 dark:bg-gray-800" />
          ) : detailCard ? (
            <section className="flex flex-col gap-4">
              {answerEntries.length > 0 && (
                <section className="rounded-xl bg-blue-50 p-3 dark:bg-blue-950/30">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    관련 정보
                  </h3>
                  <dl className="mt-2 space-y-2 text-sm">
                    {answerEntries.map(([key, value]) => (
                      <div key={key} className="flex gap-2">
                        <dt className="shrink-0 text-gray-500 dark:text-gray-400">
                          {ANSWER_FIELD_LABELS[key] ?? key}
                        </dt>
                        <AnswerValue value={value} />
                      </div>
                    ))}
                  </dl>
                </section>
              )}
              <RealtimeDetailEntries card={detailCard} />
              {((detailCard.population_forecasts?.length ?? 0) > 0 ||
                (detailCard.concentration_forecasts?.length ?? 0) > 0 ||
                detailCard.question_type === "realtime_traffic") && (
                <section className="overflow-hidden rounded-xl border border-gray-100 bg-white dark:border-gray-800 dark:bg-gray-900">
                  <ConcentrationForecastBars card={detailCard} />
                  <PopulationForecastBars card={detailCard} />
                  <RoadTrafficStatusSection card={detailCard} />
                </section>
              )}
              {detailCard.overview && (
                <section>
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">개요</h3>
                  <p className="mt-1 whitespace-pre-line text-sm leading-6 text-gray-700 dark:text-gray-300">
                    {detailCard.overview}
                  </p>
                </section>
              )}
              <PreferenceInsightsSection card={detailCard} />
              <DetailEntries card={detailCard} entries={DETAIL_FIELDS} />
              <DetailEntries card={detailCard} entries={FACILITY_FIELDS} />
            </section>
          ) : (
            <p className="rounded-xl border border-dashed border-gray-300 p-4 text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400">
              {detailStatus === "unavailable"
                ? "상세 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."
                : "이 장소의 상세 정보는 아직 제공되지 않아요."}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
