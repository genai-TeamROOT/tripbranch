/*
 * 역할: INFO 장소 질의의 간략 답변과 전체 장소 상세 정보를 한 카드에 표시한다.
 * 입력: C가 한 번의 상세 조회로 내려준 InfoPlaceCard.
 * 출력: 질문 답 요약과 클릭 시 열리는 장소 상세 모달.
 * 호출 시점: ChatMessageList가 place_info_result 메시지를 렌더할 때 호출된다.
 */

import { useState } from "react";
import type { InfoPlaceCard as InfoPlaceCardData } from "../../types";
import { RecommendationDetailPreviewModal } from "./RecommendationDetailPreviewModal";

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

interface PlaceInfoCardProps {
  card: InfoPlaceCardData;
}

interface OperatingHoursRow {
  period: string;
  hours: string;
}

function parseOperatingHours(value: string): OperatingHoursRow[] | null {
  // TourAPI는 "[기간]시간[기간]시간"처럼 구분자 없이 이어 붙여 내려준다.
  // 원문은 바꾸지 않고 카드에서만 기간별 행으로 나눈다.
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

function formatCardValue(fieldKey: keyof InfoPlaceCardData, value: string) {
  // TourAPI 원문의 예외 안내(※)는 문장에 붙여 두면 읽기 어렵다. 원문 뜻은
  // 바꾸지 않고 줄만 분리한다. 요금의 "-" 항목도 카드에서 불릿처럼 보이게 한다.
  let formatted = value.replace(/\s*※\s*/g, "\n※ ");
  if (fieldKey === "fee") {
    formatted = formatted.replace(/(?:^|\s)-\s*/g, "\n- ");
  }
  return formatted.trim();
}

export function PlaceInfoCard({ card }: PlaceInfoCardProps) {
  const [showDetail, setShowDetail] = useState(false);
  const answers = Object.entries(card.answer_fields);

  return (
    <article className="mr-auto w-full max-w-xl overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900">
      {card.thumbnail_url && (
        // 기본 카드에서 장소를 바로 알아볼 수 있도록, 작은 아이콘보다 충분히 큰
        // 중간 높이 썸네일을 카드 상단에 둔다. 상세 영역에서는 중복하지 않는다.
        <div className="flex h-44 w-full items-center justify-center overflow-hidden bg-gray-100 dark:bg-gray-800">
          <img
            src={card.thumbnail_url}
            alt={`${card.place_name ?? "장소"} 이미지`}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        </div>
      )}
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        aria-haspopup="dialog"
        aria-label={`${card.place_name ?? "장소"} 상세 보기`}
        onClick={() => setShowDetail(true)}
      >
        <span className="min-w-0 text-sm font-semibold text-gray-900 dark:text-gray-100">
          {card.place_name ?? "장소 상세 정보"}
        </span>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-300">
          상세 보기
          <span aria-hidden="true">↗</span>
        </span>
      </button>

      {answers.length > 0 && (
        <dl className="border-t border-gray-100 px-4 py-3 text-sm dark:border-gray-800">
          {answers.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className="shrink-0 text-gray-500 dark:text-gray-400">
                {FIELD_LABELS[key] ?? key}
              </dt>
              <dd className="min-w-0 flex-1 whitespace-pre-line text-gray-800 dark:text-gray-100">
                {key === "operating_hours" && parseOperatingHours(value) ? (
                  <OperatingHoursRows rows={parseOperatingHours(value) ?? []} />
                ) : (
                  formatCardValue(key as keyof InfoPlaceCardData, value)
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {showDetail && (
        <RecommendationDetailPreviewModal card={card} onClose={() => setShowDetail(false)} />
      )}
    </article>
  );
}
