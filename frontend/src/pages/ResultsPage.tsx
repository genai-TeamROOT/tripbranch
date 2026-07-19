// 세 번째 화면("/results"): 추천 결과(recommendations)와 운영시간 미확인 목록
// (unverified_recommendations)을 구분해서 보여준다. "다른 장소 보기"는 같은 조건 +
// 누적된 shown_place_ids로 재요청하고, 결과가 0개면 검색 반경을 넓혀 재시도하는 버튼을 노출한다.
// TODO: 반경 확대 외의 조건 완화(카테고리 완화, 날씨 무시 등) 선택지는 아직 없음 -
// 필요해지면 hasNoResults 분기 안에 옵션을 추가할 것.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getRecommendations } from "../api/recommendations";
import { ApiError } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { PlaceCard } from "../components/PlaceCard";
import { useTripDispatch } from "../context/useTripDispatch";
import { useTripState } from "../context/useTripState";

const RADIUS_RELAXATION_STEP_KM = 0.5;

export function ResultsPage() {
  const state = useTripState();
  const dispatch = useTripDispatch();
  const navigate = useNavigate();

  const conditions = state.interpreted_conditions!;

  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const hasNoResults =
    state.recommendation_results.length === 0 && state.unverified_recommendations.length === 0;

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
          type: "UPDATE_INTERPRETED_CONDITIONS",
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
              {state.recommendation_results.map((item) => (
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
