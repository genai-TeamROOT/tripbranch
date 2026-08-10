/*
 * 역할: 추천 장소 하나를 카드 형태로 렌더링한다.
 * 입력: RecommendationItem 데이터와 운영시간 미확인 표시 여부.
 * 출력: 장소명, 카테고리, 추천 이유, 주소, 검증 상태 UI.
 * 호출 시점: RecommendationResultMessage가 추천 목록과 검증 불가 목록을 표시할 때 호출된다.
 * TODO: 지도 링크, 저장/제외 액션, 실시간 영업 정보가 생기면 하위 UI를 확장한다.
 */

import type { RecommendationItem } from "../types";

/*
 * 신호 대기·혼잡·길 찾기 여유를 포함한 보수적 보행 속도. 성인 여성의 일반적인
 * 보행 속도보다 낮은 3.6km/h(1km 약 17분)로 잡아 실제 이동시간을 낙관적으로
 * 안내하지 않는다.
 */
const SAFE_WALKING_SPEED_KMH = 3.6;

interface PlaceCardProps {
  item: RecommendationItem;
  unverifiedHours?: boolean;
}

function formatWalkingMinutes(distanceKm: number): string {
  const minutes = Math.max(1, Math.ceil((distanceKm / SAFE_WALKING_SPEED_KMH) * 60));
  return `약 ${minutes}분`;
}

function formatRemainingDuration(remainingMinutes: number): string {
  // 카드에서는 분 단위 정밀도보다 빠른 비교가 중요하므로, 가장 가까운 시간으로
  // 반올림한다. 운영 종료가 임박한 경우 0시간으로 보이지 않도록 최소 1시간이다.
  const hours = Math.max(1, Math.round(remainingMinutes / 60));
  return `${hours}시간 남음`;
}

function formatClosingTime(remainingMinutes: number): string {
  const closesAt = new Date(Date.now() + remainingMinutes * 60 * 1000);
  const time = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(closesAt);
  return `운영 종료 예정 ${time} (${formatRemainingDuration(remainingMinutes)})`;
}

function formatOperatingHours(item: RecommendationItem): string {
  if (item.remaining_minutes === null) {
    return "확인 불가";
  }

  // D가 제공하는 당일 적용 운영 구간을 우선 표시한다. 이전 응답 또는 구간을
  // 판별할 수 없는 후보는 기존의 종료 예정 시각 표기로 자연스럽게 폴백한다.
  if (item.operating_hours_display) {
    return `${item.operating_hours_display} (${formatRemainingDuration(item.remaining_minutes)})`;
  }

  return formatClosingTime(item.remaining_minutes);
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
          <dt className="text-gray-400">도보 이동</dt>
          <dd>{formatWalkingMinutes(item.distance_km)}</dd>
        </div>
        <div className="flex gap-1">
          <dt className="text-gray-400">운영시간</dt>
          <dd>
            {unverifiedHours ? "확인 불가" : formatOperatingHours(item)}
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
