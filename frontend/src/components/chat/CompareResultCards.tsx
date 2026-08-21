/*
 * 역할: COMPARE(TRAVEL_TIME) 응답의 장소별 실측 거리·수단별 소요시간을 카드로 보여준다.
 * 입력: ComparisonResult(비교 기준 + 장소별 비교 사실).
 * 출력: 비교 대상 장소마다 거리·도보/자동차/대중교통 소요시간을 한눈에 보는 카드 목록.
 * 호출 시점: ChatMessageList가 compare_result 메시지를 렌더링할 때 호출된다.
 *
 * criteria=travel_time일 때만 의미 있는 카드다(travel_* 필드가 이때만 채워진다).
 * time/overall 비교는 기존처럼 답변 문장만으로 충분하다고 보고 카드를 만들지 않는다
 * — 사용자 요청은 "이동 용이성 비교가 텍스트로만 오니 안 와닿는다"는 것이었다.
 */

import type { ComparisonItem, ComparisonResult } from "../../types";

interface CompareResultCardsProps {
  comparison: ComparisonResult;
}

const TRAVEL_MODES: {
  label: string;
  field: keyof Pick<
    ComparisonItem,
    "travel_walking_minutes" | "travel_driving_minutes" | "travel_transit_minutes"
  >;
}[] = [
  { label: "도보", field: "travel_walking_minutes" },
  { label: "자동차", field: "travel_driving_minutes" },
  { label: "대중교통", field: "travel_transit_minutes" },
];

function fastestMinutes(item: ComparisonItem): number | null {
  const values = TRAVEL_MODES.map(({ field }) => item[field]).filter(
    (value): value is number => value !== null,
  );
  return values.length > 0 ? Math.min(...values) : null;
}

function CompareTravelCard({ item, isFastest }: { item: ComparisonItem; isFastest: boolean }) {
  const modeEntries = TRAVEL_MODES.map(({ label, field }) => ({ label, minutes: item[field] })).filter(
    (entry): entry is { label: string; minutes: number } => entry.minutes !== null,
  );

  return (
    <li
      className={`flex flex-col gap-2 rounded-lg border p-3 shadow-sm ${
        isFastest
          ? "border-blue-300 bg-blue-50/40 dark:border-blue-700 dark:bg-blue-950/20"
          : "border-gray-200 dark:border-gray-700"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{item.place_name}</p>
        {isFastest && (
          <span className="rounded bg-blue-600 px-1.5 py-0.5 text-[11px] font-medium text-white">
            가장 빠름
          </span>
        )}
      </div>

      {item.travel_distance_km !== null && (
        <p className="text-xs text-gray-500 dark:text-gray-400">약 {item.travel_distance_km}km</p>
      )}

      {modeEntries.length > 0 ? (
        <dl className="grid grid-cols-3 gap-2">
          {modeEntries.map(({ label, minutes }) => (
            <div key={label} className="flex flex-col items-center gap-0.5 rounded bg-gray-50 py-1.5 dark:bg-gray-800">
              <dt className="text-[11px] text-gray-500 dark:text-gray-400">{label}</dt>
              <dd className="text-sm font-medium text-gray-900 dark:text-gray-100">{minutes}분</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-xs text-gray-500 dark:text-gray-400">이동 경로를 확인하지 못했어요.</p>
      )}
    </li>
  );
}

export function CompareResultCards({ comparison }: CompareResultCardsProps) {
  if (comparison.criteria !== "travel_time") return null;

  const fastest = Math.min(
    ...comparison.items.map(fastestMinutes).filter((value): value is number => value !== null),
  );

  return (
    <ul className="mr-auto grid w-full max-w-xl grid-cols-1 gap-2 sm:grid-cols-2">
      {comparison.items.map((item) => (
        <CompareTravelCard
          key={item.place_id}
          item={item}
          isFastest={Number.isFinite(fastest) && fastestMinutes(item) === fastest}
        />
      ))}
    </ul>
  );
}
