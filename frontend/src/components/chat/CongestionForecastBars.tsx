/*
 * 역할: 실시간 인구 혼잡도·관광지 집중률 예측을 시각적으로 보여준다.
 * 입력: InfoPlaceCard의 population_* / concentration_* 필드.
 * 출력: 현재 단계 게이지 + 색상이 단계별로 다른 예측 막대그래프.
 * 호출 시점: PlaceInfoCard(요약 카드)와 RecommendationDetailPreviewModal(상세 모달) 양쪽.
 */

import { useState } from "react";
import type { InfoPlaceCard as InfoPlaceCardData } from "../../types";
import {
  AXIS_TICK_COUNT,
  axisCeiling,
  axisLabel,
  formatPopulationRange,
  populationMidpoint,
} from "../../utils/seoulRealtimeDisplay";


/*
 * 서울시 인구 혼잡도 원문 단계(한글) → 팔레트 색상.
 * amber-400/orange-500을 쓰면 가운데 두 단계가 거의 같은 색으로 보인다 — 토큰
 * 팔레트가 amber-500과 orange-500을 둘 다 gold(#e0a83e)로 재정의하기 때문이다.
 * 옅은 앰버(300)와 진한 앰버(500)로 간격을 벌려 네 단계가 서로 구분되게 한다.
 */
const POPULATION_LEVEL_COLOR: Record<string, { bar: string; track: string }> = {
  여유: { bar: "bg-emerald-500", track: "bg-emerald-50 dark:bg-emerald-950/30" },
  보통: { bar: "bg-amber-300", track: "bg-amber-50 dark:bg-amber-950/30" },
  "약간 붐빔": { bar: "bg-amber-500", track: "bg-amber-100 dark:bg-amber-950/30" },
  붐빔: { bar: "bg-red-500", track: "bg-red-50 dark:bg-red-950/30" },
};

/** app/concentration_policy.py의 ConcentrationLevel 영문 코드 → 팔레트 색상. */
const CONCENTRATION_LEVEL_COLOR: Record<string, { bar: string; track: string }> = {
  quiet: { bar: "bg-emerald-500", track: "bg-emerald-50 dark:bg-emerald-950/30" },
  normal: { bar: "bg-amber-300", track: "bg-amber-50 dark:bg-amber-950/30" },
  slightly_crowded: { bar: "bg-amber-500", track: "bg-amber-100 dark:bg-amber-950/30" },
  crowded: { bar: "bg-red-500", track: "bg-red-50 dark:bg-red-950/30" },
};

const UNKNOWN_LEVEL_COLOR = { bar: "bg-gray-400", track: "bg-gray-50 dark:bg-gray-800/60" };

const CONGESTION_HEIGHT: Record<string, number> = {
  여유: 25,
  보통: 45,
  "약간 붐빔": 70,
  붐빔: 92,
};

/** 인구 혼잡도 게이지의 4단계 순서. 마커 위치도 이 순서 기준 인덱스로 계산한다. */
const POPULATION_GAUGE_LEVELS: Array<{ label: string; color: string }> = [
  { label: "여유", color: "bg-emerald-500" },
  { label: "보통", color: "bg-amber-300" },
  { label: "약간 붐빔", color: "bg-amber-500" },
  { label: "붐빔", color: "bg-red-500" },
];

/** 도로소통 게이지의 3단계 순서(ROAD_TRAFFIC_IDX 원문 그대로). */
const TRAFFIC_GAUGE_LEVELS: Array<{ label: string; color: string }> = [
  { label: "원활", color: "bg-emerald-500" },
  { label: "서행", color: "bg-amber-500" },
  { label: "정체", color: "bg-red-500" },
];

function hourLabel(value: string) {
  const match = value.match(/(\d{2}):(\d{2})/);
  return match ? `${Number(match[1])}시` : value;
}

function dateLabel(value: string) {
  const match = value.match(/(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${Number(match[2])}/${Number(match[3])}` : value;
}

/*
 * 단계 칩 색. 토큰 팔레트 안에서 "옅은 초록 → 옅은 앰버 → 진한 앰버 → 옅은 레드"로
 * 올라가게 짰다 — 막대 색(emerald→amber→orange→red)과 같은 계열이면서, 배경만
 * 옅게 깔던 기존 muted 캡션보다 글자 대비가 확실히 높다.
 */
const LEVEL_CHIP_CALM = "bg-emerald-50 text-emerald-700";
const LEVEL_CHIP_SOFT = "bg-amber-50 text-amber-700";
const LEVEL_CHIP_WARM = "bg-amber-100 text-amber-900";
const LEVEL_CHIP_BUSY = "bg-rust-tint text-rust";
const LEVEL_CHIP_NEUTRAL = "bg-chip text-label";

/**
 * 인구 혼잡도 4단계와 상권 활동 4단계를 한 표에서 본다 — 두 척도가 쓰는 낱말은
 * 다르지만(붐빔 vs 분주한) 읽는 방향은 같아서 같은 색 사다리를 태운다.
 * 서울시 원문은 "바쁜 시간대"처럼 접미사가 붙어 오기도 한다.
 */
const LEVEL_CHIP_STYLE: Record<string, string> = {
  여유: LEVEL_CHIP_CALM,
  보통: LEVEL_CHIP_SOFT,
  "약간 붐빔": LEVEL_CHIP_WARM,
  붐빔: LEVEL_CHIP_BUSY,
  한산한: LEVEL_CHIP_CALM,
  바쁜: LEVEL_CHIP_WARM,
  분주한: LEVEL_CHIP_BUSY,
  원활: LEVEL_CHIP_CALM,
  서행: LEVEL_CHIP_WARM,
  정체: LEVEL_CHIP_BUSY,
};

/** 혼잡도·상권 단계를 눈에 띄는 칩으로 보여준다. 모르는 단계는 중립색으로 둔다. */
export function CongestionLevelChip({
  level,
  prefix,
  size = "sm",
  className = "",
}: {
  level: string | null | undefined;
  prefix?: string;
  size?: "sm" | "md";
  className?: string;
}) {
  if (!level) return null;
  // "바쁜 시간대"·"보통 시간대"처럼 접미사가 붙어도 같은 단계로 읽는다.
  const normalized = level.replace(/\s*시간대$/, "");
  const style = LEVEL_CHIP_STYLE[normalized] ?? LEVEL_CHIP_NEUTRAL;
  const sizeClass = size === "md" ? "px-2.5 py-1 text-sm" : "px-2 py-0.5 text-[11px]";
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full font-semibold ${sizeClass} ${style} ${className}`}
    >
      {prefix ? `${prefix} ${level}` : level}
    </span>
  );
}

/** 현재 단계가 주어진 순서형 척도(예: 여유~붐빔, 원활~정체) 중 어디인지 보여주는 가로 게이지. */
export function CongestionLevelGauge({
  level,
  levels = POPULATION_GAUGE_LEVELS,
  ariaLabelPrefix = "현재 인구 혼잡도",
}: {
  level: string | null | undefined;
  levels?: Array<{ label: string; color: string }>;
  ariaLabelPrefix?: string;
}) {
  if (!level) return null;
  const activeIndex = levels.findIndex((entry) => entry.label === level);

  return (
    <div className="mt-2" aria-label={`${ariaLabelPrefix} ${level}`}>
      {activeIndex >= 0 && (
        <div
          className="flex text-rust transition-transform"
          style={{
            transform: `translateX(calc(${activeIndex} * 100%))`,
            width: `${100 / levels.length}%`,
          }}
        >
          <span className="mx-auto text-xs" aria-hidden="true">
            ▼
          </span>
        </div>
      )}
      <div className="flex overflow-hidden rounded-full">
        {levels.map((entry) => (
          <div key={entry.label} className={`h-2 flex-1 ${entry.color}`} />
        ))}
      </div>
      <div className="mt-1 flex text-[10px] text-muted">
        {levels.map((entry) => (
          <span
            key={entry.label}
            className={`flex-1 text-center ${
              entry.label === level ? "font-semibold text-ink" : ""
            }`}
          >
            {entry.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** 도로소통 단계·평균속도·안내문구를 카드에 시각적으로 보여준다. */
export function RoadTrafficStatusSection({ card }: { card: InfoPlaceCardData }) {
  if (card.question_type !== "realtime_traffic") return null;
  const level = card.answer_fields["도로소통 단계"];
  if (!level) return null;
  const speed = card.answer_fields["평균 주행속도"];
  const message = card.answer_fields["안내"];

  return (
    <section className="border-t border-border px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-bold text-ink">도로소통 현황</h3>
        <div className="flex shrink-0 items-center gap-1.5">
          {speed && <span className="text-xs text-muted">평균 {speed}</span>}
          <CongestionLevelChip level={level} />
        </div>
      </div>
      <CongestionLevelGauge
        level={level}
        levels={TRAFFIC_GAUGE_LEVELS}
        ariaLabelPrefix="현재 도로소통 단계"
      />
      {message && <p className="mt-2 text-xs text-muted">{message}</p>}
    </section>
  );
}

export function ConcentrationForecastBars({ card }: { card: InfoPlaceCardData }) {
  const forecasts = card.concentration_forecasts ?? [];
  if (forecasts.length === 0) return null;
  return (
    <section className="border-t border-border px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-bold text-ink">관광지 혼잡도 예측</h3>
        <span className="text-xs text-muted">방문 예정일 포함 {forecasts.length}일</span>
      </div>
      <div className="mt-3 flex h-28 items-end gap-1.5" aria-label="관광지 혼잡도 7일 예측">
        {forecasts.map((forecast) => {
          const height = Math.max(14, Math.min(100, forecast.concentration_rate));
          const color =
            CONCENTRATION_LEVEL_COLOR[forecast.concentration_level] ?? UNKNOWN_LEVEL_COLOR;
          return (
            <div
              key={forecast.forecast_date}
              className="flex min-w-0 flex-1 flex-col items-center gap-1"
            >
              <div className={`flex h-16 w-full items-end rounded-t px-0.5 ${color.track}`}>
                <div
                  className={`w-full rounded-t ${color.bar}`}
                  style={{ height: `${height}%` }}
                  title={`${dateLabel(forecast.forecast_date)} ${forecast.concentration_label}`}
                />
              </div>
              <span className="text-[10px] font-medium text-muted">
                {dateLabel(forecast.forecast_date)}
              </span>
              <span className="truncate text-[10px] text-muted">
                {forecast.concentration_label}
              </span>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-muted">관광지 집중률 예측 · 한국관광공사 데이터 기반</p>
    </section>
  );
}

/**
 * "현재" 막대를 예측과 갈라 보이는 점선 구분선. 막대 행과 라벨 행에 같이 걸어야
 * 두 행의 칸 폭이 어긋나지 않는다(border-box라 폭은 그대로 유지된다).
 */
const CURRENT_COLUMN_CLASS = "border-r-2 border-dashed border-border pr-1.5";

/** 막대에 커서를 올렸을 때 뜨는 말풍선. 시각·혼잡도·인구수를 그대로 보여준다. */
function PopulationBarTooltip({
  column,
  index,
  total,
  barColor,
}: {
  column: PopulationBarColumn;
  index: number;
  total: number;
  barColor: string;
}) {
  const range = formatPopulationRange(column.populationMin, column.populationMax);
  // 양 끝 막대는 가운데 정렬하면 카드 밖으로 삐져나간다 — 끝에 붙여 세운다.
  const edge =
    index === 0
      ? "left-0"
      : index === total - 1
        ? "right-0"
        : "left-1/2 -translate-x-1/2";
  return (
    <div
      role="tooltip"
      className={`absolute bottom-full z-10 mb-1.5 w-max max-w-[11rem] rounded-lg border border-border bg-surface px-2.5 py-1.5 shadow-card ${edge}`}
    >
      <p className="text-[11px] font-bold text-ink">{column.label}</p>
      {column.level && (
        <p className="mt-0.5 flex items-center gap-1 text-[11px] text-muted">
          혼잡도
          <span className={`h-1.5 w-1.5 rounded-full ${barColor}`} aria-hidden="true" />
          <span className="font-semibold text-label">{column.level}</span>
        </p>
      )}
      {range && (
        <p className="mt-0.5 text-[11px] text-muted">
          인구수 <span className="font-semibold text-label">{range}</span>
        </p>
      )}
    </div>
  );
}

interface PopulationBarColumn {
  key: string;
  label: string;
  /** 축 아래에 시각을 적을지. 잘리지 않게 솎아낸다 — 라벨 칸 자체는 그대로 둔다. */
  labelShown: boolean;
  level: string;
  populationMin: number | null;
  populationMax: number | null;
  isCurrent: boolean;
}

export function PopulationForecastBars({ card }: { card: InfoPlaceCardData }) {
  // 커서를 올린(또는 탭·포커스한) 막대. 터치 기기에는 hover가 없어 클릭으로도 연다.
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const forecasts = card.population_forecasts ?? [];
  if (forecasts.length === 0) return null;

  const summary = card.seoul_realtime_summary;
  const columns: PopulationBarColumn[] = [
    ...(card.population_current_level
      ? [
          {
            key: "current",
            label: "현재",
            level: card.population_current_level,
            populationMin: summary?.population_min ?? null,
            populationMax: summary?.population_max ?? null,
            labelShown: true,
            isCurrent: true,
          },
        ]
      : []),
    ...forecasts.map((forecast, index) => ({
      key: forecast.forecast_at,
      label: hourLabel(forecast.forecast_at),
      // 12슬롯을 다 적으면 칸 폭보다 글자가 길어 "20…"으로 잘린다. 세 칸에 하나만
      // 적어 눈금처럼 쓰고, 정확한 시각은 막대 말풍선이 알려준다.
      labelShown: index % 3 === 0,
      level: forecast.congestion_level ?? "",
      populationMin: forecast.population_min ?? null,
      populationMax: forecast.population_max ?? null,
      isCurrent: false,
    })),
  ];

  // 막대 하나라도 인구 수가 비면 세로축을 세우지 않는다. 일부만 실제 수치이고
  // 나머지는 단계로 어림한 높이면, 눈금이 붙은 순간 전부 실측치처럼 읽힌다.
  const midpoints = columns.map((column) =>
    populationMidpoint(column.populationMin, column.populationMax),
  );
  const hasFullScale = midpoints.every((value) => value != null && value > 0);
  const ceiling = hasFullScale ? axisCeiling(Math.max(...(midpoints as number[]))) : 0;
  const ticks =
    ceiling > 0
      ? Array.from({ length: AXIS_TICK_COUNT + 1 }, (_, index) => ({
          ratio: index / AXIS_TICK_COUNT,
          value: (ceiling / AXIS_TICK_COUNT) * index,
        }))
      : [];

  return (
    <section className="border-t border-border px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-bold text-ink">인구 혼잡도 예측</h3>
        <CongestionLevelChip level={card.population_current_level} prefix="현재" />
      </div>
      <CongestionLevelGauge level={card.population_current_level} />
      <div
        className="mt-3 flex gap-1"
        aria-label="현재부터 향후 12시간 인구 혼잡도 예측"
      >
        {ticks.length > 0 && (
          <div className="relative h-16 w-12 shrink-0" aria-hidden="true">
            {ticks.map((tick) => (
              <span
                key={tick.ratio}
                className="absolute right-1 translate-y-1/2 text-[10px] leading-none text-muted"
                style={{ bottom: `${tick.ratio * 100}%` }}
              >
                {axisLabel(tick.value)}
              </span>
            ))}
          </div>
        )}
        <div className="relative min-w-0 flex-1">
          {ticks.length > 0 && (
            <div className="pointer-events-none absolute inset-x-0 top-0 h-16" aria-hidden="true">
              {ticks.map((tick) => (
                <div
                  key={tick.ratio}
                  className="absolute inset-x-0 border-t border-border/60"
                  style={{ bottom: `${tick.ratio * 100}%` }}
                />
              ))}
            </div>
          )}
          {/* 격자선 레이어가 absolute라 static 형제보다 위에 그려진다 — 막대 행도
              positioned로 만들어 격자선이 막대 뒤로 가게 한다. */}
          <div className="relative flex h-16 items-end gap-1.5">
            {columns.map((column, index) => {
              const color = POPULATION_LEVEL_COLOR[column.level] ?? UNKNOWN_LEVEL_COLOR;
              const midpoint = midpoints[index];
              const height =
                ceiling > 0 && midpoint != null
                  ? Math.max(2, Math.min(100, (midpoint / ceiling) * 100))
                  : (CONGESTION_HEIGHT[column.level] ?? 18);
              const range = formatPopulationRange(column.populationMin, column.populationMax);
              return (
                <button
                  type="button"
                  key={column.key}
                  // 커서·포커스로 열고, hover가 없는 터치 기기에서는 탭으로 연다.
                  onMouseEnter={() => setActiveIndex(index)}
                  onMouseLeave={() => setActiveIndex(null)}
                  onFocus={() => setActiveIndex(index)}
                  onBlur={() => setActiveIndex(null)}
                  onClick={() => setActiveIndex(activeIndex === index ? null : index)}
                  // 말풍선은 커서를 올려야 보이니, 읽어주는 화면에는 같은 내용을 붙인다.
                  aria-label={[column.label, column.level, range].filter(Boolean).join(", ")}
                  className={`relative flex h-full min-w-0 flex-1 cursor-default flex-col items-center rounded-t focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                    column.isCurrent ? CURRENT_COLUMN_CLASS : ""
                  }`}
                >
                  {activeIndex === index && (
                    <PopulationBarTooltip
                      column={column}
                      index={index}
                      total={columns.length}
                      barColor={color.bar}
                    />
                  )}
                  {/* 눈금이 서면 칸 배경(track)을 지운다 — 막대 위로 옅은 색 블록이
                      남으면 격자선과 겹쳐 "저기까지 찼다"고 읽힌다. */}
                  <div
                    className={`flex h-full w-full items-end rounded-t px-0.5 ${
                      ceiling > 0 ? "" : color.track
                    }`}
                  >
                    <div
                      data-population-bar={column.key}
                      // "현재" 강조는 칸이 아니라 막대에 건다. 칸에 걸면 축이 선
                      // 뒤에는 테두리가 최고 눈금까지 올라가 실제보다 많아 보인다.
                      className={`w-full rounded-t ${color.bar} ${
                        column.isCurrent ? "ring-2 ring-inset ring-ink" : ""
                      }`}
                      style={{ height: `${height}%` }}
                    />
                  </div>
                </button>
              );
            })}
          </div>
          <div className="mt-1 flex gap-1.5">
            {columns.map((column) => (
              <span
                key={column.key}
                className={`min-w-0 flex-1 truncate text-center text-[10px] ${
                  column.isCurrent ? `font-semibold text-ink ${CURRENT_COLUMN_CLASS}` : "text-muted"
                }`}
              >
                {column.labelShown ? column.label : ""}
              </span>
            ))}
          </div>
        </div>
      </div>
      {ticks.length > 0 && (
        // 막대 높이와 색이 서로 다른 값을 말하게 됐으니 무엇이 무엇인지 밝힌다.
        // 서울시는 현재 단계(AREA_CONGEST_LVL)와 예측 단계(FCST_CONGEST_LVL)를 따로
        // 산출해서, 단계가 더 높은데 인구 수는 더 적은 구간이 실제로 나온다
        // (2026-09-05 실측: 8개 지역 중 난지한강공원·동대문 관광특구 2곳).
        <p className="mt-2 text-[11px] text-muted">
          막대 높이는 인구 수, 색은 서울시 혼잡도 단계예요 — 두 값을 따로 산출해 가끔
          어긋나요.
        </p>
      )}
      <p className="mt-2 text-xs text-muted">
        향후 12시간 인구 혼잡도 예측 · 통신 데이터 기반
        {card.population_observed_at ? ` · ${card.population_observed_at} 기준` : ""}
      </p>
      {card.population_peak_forecast_summary && (
        <p className="mt-1 text-xs font-semibold text-label">
          {card.population_peak_forecast_summary}
        </p>
      )}
    </section>
  );
}
