/*
 * 역할: 실시간 인구 혼잡도·관광지 집중률 예측을 시각적으로 보여준다.
 * 입력: InfoPlaceCard의 population_* / concentration_* 필드.
 * 출력: 현재 단계 게이지 + 색상이 단계별로 다른 예측 막대그래프.
 * 호출 시점: PlaceInfoCard(요약 카드)와 RecommendationDetailPreviewModal(상세 모달) 양쪽.
 */

import type { InfoPlaceCard as InfoPlaceCardData } from "../../types";

/** 서울시 인구 혼잡도 원문 단계(한글) → 팔레트 색상. */
const POPULATION_LEVEL_COLOR: Record<string, { bar: string; track: string }> = {
  "여유": { bar: "bg-emerald-500", track: "bg-emerald-50 dark:bg-emerald-950/30" },
  "보통": { bar: "bg-amber-400", track: "bg-amber-50 dark:bg-amber-950/30" },
  "약간 붐빔": { bar: "bg-orange-500", track: "bg-orange-50 dark:bg-orange-950/30" },
  "붐빔": { bar: "bg-red-500", track: "bg-red-50 dark:bg-red-950/30" },
};

/** app/concentration_policy.py의 ConcentrationLevel 영문 코드 → 팔레트 색상. */
const CONCENTRATION_LEVEL_COLOR: Record<string, { bar: string; track: string }> = {
  quiet: { bar: "bg-emerald-500", track: "bg-emerald-50 dark:bg-emerald-950/30" },
  normal: { bar: "bg-amber-400", track: "bg-amber-50 dark:bg-amber-950/30" },
  slightly_crowded: { bar: "bg-orange-500", track: "bg-orange-50 dark:bg-orange-950/30" },
  crowded: { bar: "bg-red-500", track: "bg-red-50 dark:bg-red-950/30" },
};

const UNKNOWN_LEVEL_COLOR = { bar: "bg-gray-400", track: "bg-gray-50 dark:bg-gray-800/60" };

const CONGESTION_HEIGHT: Record<string, number> = {
  "여유": 25,
  "보통": 45,
  "약간 붐빔": 70,
  "붐빔": 92,
};

/** 게이지에 표시할 4단계 순서. 마커 위치도 이 순서 기준 인덱스로 계산한다. */
const GAUGE_LEVELS: Array<{ label: string; color: string }> = [
  { label: "여유", color: "bg-emerald-500" },
  { label: "보통", color: "bg-amber-400" },
  { label: "약간 붐빔", color: "bg-orange-500" },
  { label: "붐빔", color: "bg-red-500" },
];

function hourLabel(value: string) {
  const match = value.match(/(\d{2}):(\d{2})/);
  return match ? `${Number(match[1])}시` : value;
}

function dateLabel(value: string) {
  const match = value.match(/(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${Number(match[2])}/${Number(match[3])}` : value;
}

/** 현재 인구 혼잡도가 여유~붐빔 4단계 중 어디인지 보여주는 가로 게이지. */
export function CongestionLevelGauge({ level }: { level: string | null | undefined }) {
  if (!level) return null;
  const activeIndex = GAUGE_LEVELS.findIndex((entry) => entry.label === level);

  return (
    <div className="mt-2" aria-label={`현재 인구 혼잡도 ${level}`}>
      {activeIndex >= 0 && (
        <div
          className="flex text-red-600 transition-transform dark:text-red-400"
          style={{
            transform: `translateX(calc(${activeIndex} * 100%))`,
            width: `${100 / GAUGE_LEVELS.length}%`,
          }}
        >
          <span className="mx-auto text-xs" aria-hidden="true">▼</span>
        </div>
      )}
      <div className="flex overflow-hidden rounded-full">
        {GAUGE_LEVELS.map((entry) => (
          <div key={entry.label} className={`h-2 flex-1 ${entry.color}`} />
        ))}
      </div>
      <div className="mt-1 flex text-[10px] text-gray-500 dark:text-gray-400">
        {GAUGE_LEVELS.map((entry) => (
          <span
            key={entry.label}
            className={`flex-1 text-center ${
              entry.label === level ? "font-semibold text-gray-900 dark:text-gray-100" : ""
            }`}
          >
            {entry.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function ConcentrationForecastBars({ card }: { card: InfoPlaceCardData }) {
  const forecasts = card.concentration_forecasts ?? [];
  if (forecasts.length === 0) return null;
  return (
    <section className="border-t border-gray-100 px-4 py-3 dark:border-gray-800">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">관광지 혼잡도 예측</h3>
        <span className="text-xs text-gray-500 dark:text-gray-400">방문 예정일 포함 {forecasts.length}일</span>
      </div>
      <div className="mt-3 flex h-28 items-end gap-1.5" aria-label="관광지 혼잡도 7일 예측">
        {forecasts.map((forecast) => {
          const height = Math.max(14, Math.min(100, forecast.concentration_rate));
          const color = CONCENTRATION_LEVEL_COLOR[forecast.concentration_level] ?? UNKNOWN_LEVEL_COLOR;
          return (
            <div key={forecast.forecast_date} className="flex min-w-0 flex-1 flex-col items-center gap-1">
              <div className={`flex h-16 w-full items-end rounded-t px-0.5 ${color.track}`}>
                <div
                  className={`w-full rounded-t ${color.bar}`}
                  style={{ height: `${height}%` }}
                  title={`${dateLabel(forecast.forecast_date)} ${forecast.concentration_label}`}
                />
              </div>
              <span className="text-[10px] font-medium text-gray-600 dark:text-gray-300">
                {dateLabel(forecast.forecast_date)}
              </span>
              <span className="truncate text-[10px] text-gray-500 dark:text-gray-400">
                {forecast.concentration_label}
              </span>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        관광지 집중률 예측 · 한국관광공사 데이터 기반
      </p>
    </section>
  );
}

export function PopulationForecastBars({ card }: { card: InfoPlaceCardData }) {
  const forecasts = card.population_forecasts ?? [];
  if (forecasts.length === 0) return null;
  return (
    <section className="border-t border-gray-100 px-4 py-3 dark:border-gray-800">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">인구 혼잡도 예측</h3>
        {card.population_current_level && (
          <span className="text-xs text-gray-500 dark:text-gray-400">현재 {card.population_current_level}</span>
        )}
      </div>
      <CongestionLevelGauge level={card.population_current_level} />
      <div className="mt-3 flex h-24 items-end gap-1.5" aria-label="현재부터 향후 12시간 인구 혼잡도 예측">
        {card.population_current_level && (
          <div className="flex min-w-0 flex-1 flex-col items-center gap-1 border-r-2 border-dashed border-gray-300 pr-1.5 dark:border-gray-600">
            {(() => {
              const level = card.population_current_level ?? "";
              const height = CONGESTION_HEIGHT[level] ?? 18;
              const color = POPULATION_LEVEL_COLOR[level] ?? UNKNOWN_LEVEL_COLOR;
              return (
                <div
                  className={`flex h-16 w-full items-end rounded-t px-0.5 ring-2 ring-inset ring-gray-900 dark:ring-gray-100 ${color.track}`}
                >
                  <div className={`w-full rounded-t ${color.bar}`} style={{ height: `${height}%` }} />
                </div>
              );
            })()}
            <span className="truncate text-[10px] font-semibold text-gray-900 dark:text-gray-100">현재</span>
          </div>
        )}
        {forecasts.map((forecast) => {
          const level = forecast.congestion_level ?? "";
          const height = CONGESTION_HEIGHT[level] ?? 18;
          const color = POPULATION_LEVEL_COLOR[level] ?? UNKNOWN_LEVEL_COLOR;
          return (
            <div key={forecast.forecast_at} className="flex min-w-0 flex-1 flex-col items-center gap-1">
              <div className={`flex h-16 w-full items-end rounded-t px-0.5 ${color.track}`}>
                <div className={`w-full rounded-t ${color.bar}`} style={{ height: `${height}%` }} />
              </div>
              <span className="truncate text-[10px] text-gray-500 dark:text-gray-400">{hourLabel(forecast.forecast_at)}</span>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        향후 12시간 인구 혼잡도 예측 · 통신 데이터 기반
        {card.population_observed_at ? ` · ${card.population_observed_at} 기준` : ""}
      </p>
      {card.population_peak_forecast_summary && (
        <p className="mt-1 text-xs font-semibold text-gray-700 dark:text-gray-200">
          {card.population_peak_forecast_summary}
        </p>
      )}
    </section>
  );
}
