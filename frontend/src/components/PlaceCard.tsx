/*
 * 역할: 추천 장소 하나를 카드 형태로 렌더링한다.
 * 입력: RecommendationItem 데이터와 운영시간 미확인 표시 여부.
 * 출력: 장소명, 카테고리, 추천 이유, 주소, 검증 상태 UI.
 * 호출 시점: ResultsPage가 추천 목록과 검증 불가 목록을 표시할 때 호출된다.
 * TODO: 지도 링크, 저장/제외 액션, 실시간 영업 정보가 생기면 하위 UI를 확장한다.
 */

import type { RecommendationItem } from "../types";

interface PlaceCardProps {
  item: RecommendationItem;
  unverifiedHours?: boolean;
}

export function PlaceCard({ item, unverifiedHours = false }: PlaceCardProps) {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-gray-200 p-4 shadow-sm dark:border-gray-700">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">{item.name}</h3>
        <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-300">
          {item.category}
        </span>
      </div>

      <p className="text-sm text-gray-600 dark:text-gray-400">{item.recommendation_reason}</p>

      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-700 dark:text-gray-300">
        <div className="flex gap-1">
          <dt className="text-gray-400">직선거리</dt>
          <dd>{item.distance_km.toFixed(2)}km</dd>
        </div>
        <div className="flex gap-1">
          <dt className="text-gray-400">남은 운영시간</dt>
          <dd>
            {unverifiedHours || item.remaining_minutes === null
              ? "확인 불가"
              : `${item.remaining_minutes}분`}
          </dd>
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
    </li>
  );
}
