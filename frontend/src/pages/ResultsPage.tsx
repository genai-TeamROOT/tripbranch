/*
 * 역할: 추천 장소와 검증 불가 후보를 결과 화면에 렌더링한다.
 * 입력: TripContext의 recommendations, unverified_recommendations, user_input.
 * 출력: 장소 카드 목록, 재시작/추가 추천 버튼, 빈 결과 안내.
 * 호출 시점: 추천 API 응답 이후 /results 라우트가 활성화될 때 호출된다.
 * TODO: 재추천, 필터, 지도/동선 보기 기능이 생기면 이 화면에서 연결한다.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getRecommendations } from "../api/trip";
import { ApiError } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { PlaceCard } from "../components/PlaceCard";
import { useTripDispatch, useTripState } from "../state/TripContext";

const RADIUS_RELAXATION_STEP_KM = 0.5;

export function ResultsPage() {
  const state = useTripState();
  const dispatch = useTripDispatch();
  const navigate = useNavigate();

  const conditions = state.interpreted_conditions!;

  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const hasNoResults =
    state.recommendations.length === 0 && state.unverified_recommendations.length === 0;

  async function fetchMore(searchRadiusKm: number, resetShown = false) {
    setIsLoading(true);
    setErrorMessage(null);

    try {
      const result = await getRecommendations({
        ...conditions,
        search_radius_km: searchRadiusKm,
        shown_place_ids: resetShown ? [] : state.shown_place_ids,
      });
      dispatch({ type: "SET_RECOMMENDATIONS", payload: result });
      if (searchRadiusKm !== conditions.search_radius_km) {
        dispatch({
          type: "UPDATE_CONDITIONS",
          payload: { search_radius_km: searchRadiusKm },
        });
      }
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : "추천을 불러오지 못했어요. 다시 시도해주세요.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-4 py-10">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">추천 결과</h1>
        <button
          type="button"
          onClick={() => navigate("/confirm")}
          className="shrink-0 rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700"
        >
          조건 다시 설정하기
        </button>
      </div>

      {errorMessage && (
        <ErrorBanner
          message={errorMessage}
          onRetry={() => fetchMore(conditions.search_radius_km)}
        />
      )}

      {hasNoResults && !errorMessage ? (
        <div className="flex flex-col gap-3 rounded-lg border border-gray-200 p-4 text-sm dark:border-gray-700">
          <p className="text-gray-700 dark:text-gray-300">조건에 맞는 장소를 찾지 못했어요.</p>
          <button
            type="button"
            disabled={isLoading}
            onClick={() => fetchMore(conditions.search_radius_km + RADIUS_RELAXATION_STEP_KM, true)}
            className="w-fit rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
          >
            검색 반경 넓혀서 다시 찾기 (+{RADIUS_RELAXATION_STEP_KM}km)
          </button>
        </div>
      ) : (
        <>
          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400">추천 장소</h2>
            <ul className="flex flex-col gap-3">
              {state.recommendations.map((item) => (
                <PlaceCard key={item.place_id} item={item} />
              ))}
            </ul>
          </section>

          {state.unverified_recommendations.length > 0 && (
            <section className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400">
                운영시간을 확인할 수 없는 장소
              </h2>
              <ul className="flex flex-col gap-3">
                {state.unverified_recommendations.map((item) => (
                  <PlaceCard key={item.place_id} item={item} unverifiedHours />
                ))}
              </ul>
            </section>
          )}

          <button
            type="button"
            disabled={isLoading}
            onClick={() => fetchMore(conditions.search_radius_km)}
            className="w-fit self-center rounded-md border border-gray-300 px-4 py-2 text-sm font-medium disabled:opacity-50 dark:border-gray-700"
          >
            {isLoading ? "불러오는 중..." : "다른 장소 보기"}
          </button>
        </>
      )}
    </main>
  );
}
