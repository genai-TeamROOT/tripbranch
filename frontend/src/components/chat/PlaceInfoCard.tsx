/*
 * 역할: INFO 장소 질의의 간략 답변과 전체 장소 상세 정보를 한 카드에 표시한다.
 * 입력: C가 한 번의 상세 조회로 내려준 InfoPlaceCard.
 * 출력: 접힌 답변 요약과 펼친 개요·운영·주차·요금·편의시설.
 * 호출 시점: ChatMessageList가 place_info_result 메시지를 렌더할 때 호출된다.
 */

import { useState } from "react";
import type { InfoPlaceCard as InfoPlaceCardData } from "../../types";

const FIELD_LABELS: Record<string, string> = {
  operating_hours: "운영시간",
  rest_date: "휴무일",
  fee: "요금",
  parking: "주차",
  parking_fee: "주차 요금",
  baby_carriage: "유모차",
  pet: "반려동물 동반",
  credit_card: "카드 결제",
  restroom: "화장실",
  overview: "개요",
  homepage: "홈페이지",
};

const DETAIL_FIELDS: Array<[keyof InfoPlaceCardData, string]> = [
  ["operating_hours", "운영시간"],
  ["rest_date", "휴무일"],
  ["parking", "주차"],
  ["parking_fee", "주차 요금"],
  ["fee", "요금"],
];

const FACILITY_FIELDS: Array<[keyof InfoPlaceCardData, string]> = [
  ["baby_carriage", "유모차"],
  ["pet", "반려동물 동반"],
  ["credit_card", "카드 결제"],
  ["restroom", "화장실"],
];

interface PlaceInfoCardProps {
  card: InfoPlaceCardData;
}

function DetailValues({
  card,
  entries,
}: {
  card: InfoPlaceCardData;
  entries: Array<[keyof InfoPlaceCardData, string]>;
}) {
  const visibleEntries = entries.filter(([key]) => {
    const value = card[key];
    return typeof value === "string" && value.trim();
  });
  if (visibleEntries.length === 0) return null;

  return (
    <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
      {visibleEntries.map(([key, label]) => (
        <DetailValue key={key} card={card} fieldKey={key} label={label} />
      ))}
    </dl>
  );
}

function DetailValue({
  card,
  fieldKey,
  label,
}: {
  card: InfoPlaceCardData;
  fieldKey: keyof InfoPlaceCardData;
  label: string;
}) {
  const value = card[fieldKey];
  if (typeof value !== "string") return null;

  return (
    <div className="rounded-md bg-gray-50 px-3 py-2 dark:bg-gray-800/70">
      <dt className="text-xs text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="mt-0.5 text-gray-800 dark:text-gray-100">{value}</dd>
    </div>
  );
}

export function PlaceInfoCard({ card }: PlaceInfoCardProps) {
  const [expanded, setExpanded] = useState(false);
  const answers = Object.entries(card.answer_fields);

  return (
    <article className="mr-auto w-full max-w-xl overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span>
          <span className="block text-sm font-semibold text-gray-900 dark:text-gray-100">
            {card.place_name ?? "장소 상세 정보"}
          </span>
          <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
            {expanded ? "상세 정보 접기" : "상세 정보 보기"}
          </span>
        </span>
        <span aria-hidden="true" className="text-gray-500 dark:text-gray-400">
          {expanded ? "⌃" : "⌄"}
        </span>
      </button>

      {answers.length > 0 && (
        <dl className="border-t border-gray-100 px-4 py-3 text-sm dark:border-gray-800">
          {answers.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className="shrink-0 text-gray-500 dark:text-gray-400">
                {FIELD_LABELS[key] ?? key}
              </dt>
              <dd className="text-gray-800 dark:text-gray-100">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {expanded && (
        <div className="flex flex-col gap-4 border-t border-gray-100 px-4 py-4 dark:border-gray-800">
          {card.thumbnail_url && (
            <img
              src={card.thumbnail_url}
              alt={`${card.place_name ?? "장소"} 썸네일`}
              loading="lazy"
              className="h-48 w-full rounded-md object-cover"
            />
          )}
          {card.overview && (
            <section>
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">개요</h3>
              <p className="mt-1 whitespace-pre-line text-sm leading-6 text-gray-700 dark:text-gray-300">
                {card.overview}
              </p>
            </section>
          )}
          <DetailValues card={card} entries={DETAIL_FIELDS} />
          <DetailValues card={card} entries={FACILITY_FIELDS} />
          {card.homepage && (
            <a
              href={card.homepage}
              target="_blank"
              rel="noreferrer"
              className="w-fit text-sm font-medium text-blue-700 underline underline-offset-2 dark:text-blue-300"
            >
              공식 홈페이지 보기
            </a>
          )}
        </div>
      )}
    </article>
  );
}
