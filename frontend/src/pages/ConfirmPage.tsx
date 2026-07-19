// 두 번째 화면("/confirm"): interpret 결과를 사용자가 확인/수정 후 /api/recommendations를
// 호출해 /results로 이동. 선호 카테고리는 현재 쉼표 구분 텍스트 입력으로 순서를 표현한다.
// TODO: 카테고리 우선순위를 직관적으로 조작할 수 있는 UI(드래그 정렬, 태그 추가/삭제)로
// 교체하는 게 다음 개선 방향 - 지금은 "실행 가능한 최소 구조"를 우선한 임시 구현.

import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { getRecommendations } from "../api/trip";
import { ApiError } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { useTripDispatch, useTripState } from "../state/TripContext";
import type { WeatherCondition } from "../types";

const WEATHER_OPTIONS: { value: WeatherCondition | ""; label: string }[] = [
  { value: "", label: "모름" },
  { value: "good", label: "맑음" },
  { value: "neutral", label: "보통" },
  { value: "bad", label: "나쁨" },
];

export function ConfirmPage() {
  const state = useTripState();
  const dispatch = useTripDispatch();
  const navigate = useNavigate();

  const conditions = state.interpreted_conditions!;

  const [locationQuery, setLocationQuery] = useState(conditions.location_query);
  const [radiusKm, setRadiusKm] = useState(conditions.search_radius_km);
  const [categoriesText, setCategoriesText] = useState(conditions.preferred_categories.join(", "));
  const [weather, setWeather] = useState<WeatherCondition | "">(conditions.weather_condition ?? "");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setErrorMessage(null);

    const preferredCategories = categoriesText
      .split(",")
      .map((category) => category.trim())
      .filter(Boolean);

    const updated = {
      location_query: locationQuery,
      preferred_categories: preferredCategories,
      weather_condition: weather === "" ? null : weather,
      search_radius_km: radiusKm,
    };
    dispatch({ type: "UPDATE_CONDITIONS", payload: updated });

    try {
      const result = await getRecommendations({ ...updated, shown_place_ids: [] });
      dispatch({ type: "SET_RECOMMENDATIONS", payload: result });
      navigate("/results");
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : "추천을 불러오지 못했어요. 다시 시도해주세요.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-4 px-4 py-10">
      <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">조건 확인</h1>
      <p className="text-sm text-gray-600 dark:text-gray-400">
        분석된 조건이 맞는지 확인하고, 필요하면 직접 수정해주세요.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700 dark:text-gray-300">기준 위치</span>
          <input
            value={locationQuery}
            onChange={(event) => setLocationQuery(event.target.value)}
            className="rounded-md border border-gray-300 p-2 dark:border-gray-700 dark:bg-gray-900"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700 dark:text-gray-300">검색 반경 (km)</span>
          <input
            type="number"
            min={0.1}
            step={0.1}
            value={radiusKm}
            onChange={(event) => setRadiusKm(Number(event.target.value))}
            className="rounded-md border border-gray-300 p-2 dark:border-gray-700 dark:bg-gray-900"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700 dark:text-gray-300">
            선호 카테고리 (쉼표로 구분, 순서가 우선순위예요)
          </span>
          <input
            value={categoriesText}
            onChange={(event) => setCategoriesText(event.target.value)}
            placeholder="museum, cafe"
            className="rounded-md border border-gray-300 p-2 dark:border-gray-700 dark:bg-gray-900"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700 dark:text-gray-300">날씨 상태</span>
          <select
            value={weather}
            onChange={(event) => setWeather(event.target.value as WeatherCondition | "")}
            className="rounded-md border border-gray-300 p-2 dark:border-gray-700 dark:bg-gray-900"
          >
            {WEATHER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {errorMessage && <ErrorBanner message={errorMessage} />}

        <button
          type="submit"
          disabled={isLoading}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
        >
          {isLoading ? "추천 받는 중..." : "추천 받기"}
        </button>
      </form>
    </main>
  );
}
