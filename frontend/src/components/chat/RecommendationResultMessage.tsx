/*
 * 역할: 추천 API 응답을 채팅 메시지 안에서 장소 카드 목록으로 렌더링한다.
 * 입력: 정상 추천 목록, 운영시간 미확인 목록, 추가 추천 요청 콜백.
 * 출력: 추천 결과 메시지, PlaceCard 목록, 다른 장소 보기/반경 확대 버튼.
 * 호출 시점: ChatPage가 recommendation_result 메시지를 렌더링할 때 호출된다.
 * TODO: 지도/동선/저장 액션이 생기면 PlaceCard 주변 액션으로 확장한다.
 *
 * showElapsedTime이 false면(실사용자 화면) 지연시간(elapsedMs/serverElapsedMs)을
 * 아예 렌더링하지 않는다 — 개발자 확인용 숫자가 실서비스 화면에 새던 걸 정리함.
 * /dev-chat(ChatMessageList의 isDeveloperView)에서만 true로 넘어온다.
 */

import type { RecommendationItem } from "../../types";
import { PlaceCard } from "../PlaceCard";

const RADIUS_RELAXATION_STEP_KM = 0.5;

interface RecommendationResultMessageProps {
  recommendations: RecommendationItem[];
  unverifiedRecommendations: RecommendationItem[];
  elapsedMs: number;
  serverElapsedMs: number;
  showElapsedTime?: boolean;
  isLoading: boolean;
  onRequestMore: () => void;
  onRelaxRadius: () => void;
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
  isLoading,
  onRequestMore,
  onRelaxRadius,
}: RecommendationResultMessageProps) {
  const hasNoResults = recommendations.length === 0 && unverifiedRecommendations.length === 0;

  return (
    <article className="mr-auto flex w-full max-w-2xl flex-col gap-4 rounded-md border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
          조건에 맞춰 이런 장소를 찾아봤어요.
        </p>
        {showElapsedTime && (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {formatDuration(elapsedMs)} 소요 (서버 {formatDuration(serverElapsedMs)})
          </p>
        )}
      </div>

      {hasNoResults ? (
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-gray-700 dark:text-gray-300">조건에 맞는 장소를 찾지 못했어요.</p>
          <button
            type="button"
            disabled={isLoading}
            onClick={onRelaxRadius}
            className="w-fit rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
          >
            검색 반경 넓혀서 다시 찾기 (+{RADIUS_RELAXATION_STEP_KM}km)
          </button>
        </div>
      ) : (
        <>
          {recommendations.length > 0 && (
            <section className="flex flex-col gap-3">
              <h3 className="text-sm font-semibold text-gray-500 dark:text-gray-400">추천 장소</h3>
              <ul className="flex flex-col gap-3">
                {recommendations.map((item) => (
                  <PlaceCard key={item.place_id} item={item} />
                ))}
              </ul>
            </section>
          )}

          {unverifiedRecommendations.length > 0 && (
            <section className="flex flex-col gap-3">
              <h3 className="text-sm font-semibold text-gray-500 dark:text-gray-400">
                운영시간을 확인할 수 없는 장소
              </h3>
              <ul className="flex flex-col gap-3">
                {unverifiedRecommendations.map((item) => (
                  <PlaceCard key={item.place_id} item={item} unverifiedHours />
                ))}
              </ul>
            </section>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={isLoading}
              onClick={onRequestMore}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium disabled:opacity-50 dark:border-gray-700"
            >
              {isLoading ? "불러오는 중..." : "다른 장소 보기"}
            </button>
            <span className="self-center text-xs text-gray-500 dark:text-gray-400">
              다른 조건이 있으면 아래 입력창에 이어서 적어주세요.
            </span>
          </div>
        </>
      )}
    </article>
  );
}
