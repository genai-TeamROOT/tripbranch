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
import { openNaverDirections } from "../../utils/naverDirections";
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
  return Boolean(
    card && ["location_info", "concentration", "event"].includes(card.question_type),
  );
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

const ANSWER_FIELD_LABELS: Record<string, string> = {
  address: "주소",
  concentration: "혼잡도",
  event: "행사",
  "상권 지역": "상권 지역",
  "상권 기준": "상권 기준",
  "업종": "업종",
  "실시간 활동": "실시간 활동",
  "기준 시각": "기준 시각",
  "안내": "안내",
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
          <p key={`${line}-${index}`} className="whitespace-pre-line text-gray-900 dark:text-gray-100">
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
              <dd><OperatingHoursRows rows={operatingHours} /></dd>
            ) : (
              <DetailText fieldKey={key} value={value} />
            )}
          </div>
        );
      })}
    </dl>
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

function RealtimeDetailEntries({ card }: { card: InfoPlaceCard }) {
  const items = card.realtime_detail_items ?? [];
  if (items.length === 0 && !card.realtime_map_url && !card.realtime_source_url) return null;

  return (
    <section className="rounded-xl border border-sky-100 bg-sky-50/70 p-4 dark:border-sky-900/60 dark:bg-sky-950/20">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">실시간 지역 정보</h3>
          <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-300">
            {card.realtime_area_name ?? "가까운 서울시 제공 지역"}
            {card.realtime_observed_at ? ` · ${card.realtime_observed_at} 기준` : ""}
          </p>
        </div>
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
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{item.title}</h4>
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
                      <dd className="mt-0.5 break-words text-gray-800 dark:text-gray-100">{value}</dd>
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

/** 추천/INFO 어디서 열어도 같은 모양으로 PlaceDetails를 보여주는 상세 모달이다. */
export function RecommendationDetailPreviewModal({
  item,
  card,
  onClose,
}: RecommendationDetailPreviewModalProps) {
  const { device_location } = useTripState();
  const [detailCard, setDetailCard] = useState<InfoPlaceCard | null>(card ?? null);
  const [detailStatus, setDetailStatus] = useState<"loading" | "no_data" | "unavailable">("loading");
  const placeId = card?.place_id ?? item?.place_id;
  const placeName = card?.place_name ?? item?.name;
  const title = detailCard?.place_name ?? card?.place_name ?? item?.name ?? "장소 상세 정보";
  const isLoading = detailStatus === "loading" && !detailCard;
  // 목적지 좌표와 현재 위치가 모두 있어야 길찾기 딥링크를 만들 수 있다.
  const canRoute =
    detailCard?.latitude != null && detailCard?.longitude != null && Boolean(device_location);
  // "관련 정보"(answer_fields)에서 개요는 아래 "개요" 섹션과 내용이 같아 제외한다(중복 제거).
  // 홈페이지는 answer_fields가 아니라 카드 최상위 필드다(질문 유형이 general_info가
  // 아니어도 백엔드가 채울 수 있다) — 하단 링크를 없앤 대신 여기서 합성해 넣는다.
  const answerEntries = detailCard
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
            <h2 id="recommendation-detail-title" className="truncate text-lg font-bold text-gray-900 dark:text-gray-100">
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
          ) : detailCard?.thumbnail_url ? (
            <img
              src={detailCard.thumbnail_url}
              alt={`${detailCard.place_name ?? title} 이미지`}
              className="h-56 w-full rounded-xl bg-gray-100 object-cover dark:bg-gray-800"
            />
          ) : !hasRealtimeDetails ? (
            <div className="flex h-56 items-center justify-center rounded-xl border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800/60 dark:text-gray-400">
              {detailStatus === "unavailable" ? "상세 정보를 불러오지 못했어요." : "등록된 이미지가 없어요."}
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
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">관련 정보</h3>
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
