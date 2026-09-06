/*
 * 역할: 서울시 실시간 도시데이터의 인구·상권 요약을 카드 공통 블록으로 보여준다.
 * 입력: InfoPlaceCard.seoul_realtime_summary(+ 현재 단계·기준 시각은 population_* 필드).
 * 출력: "실시간 인구"와 "실시간 상권" 두 구획. 값이 없는 구획은 통째로 감춘다.
 * 호출 시점: 실시간 혼잡도(concentration)·실시간 상권(realtime_commercial) 카드에서만 —
 *   이 두 유형만 서울시 citydata를 이미 호출하므로 추가 호출 없이 채울 수 있다.
 */

import type { InfoPlaceCard as InfoPlaceCardData } from "../../types";
import {
  formatPaymentAmountRange,
  formatPopulationRangeCompact,
} from "../../utils/seoulRealtimeDisplay";
import { CongestionLevelChip } from "./CongestionForecastBars";

/** 이 블록을 싣는 질문 유형. 나머지 INFO는 서울시 데이터를 조회하지 않는다. */
const SUPPORTED_QUESTION_TYPES = new Set(["concentration", "realtime_commercial"]);

/*
 * 값 아래 보조 정보는 두 종류다 — 혼잡도·상권 "단계"는 색 칩으로(옅은 회색 글씨로
 * 두면 정작 제일 읽히길 바라는 값이 가장 안 보인다), "329건"·"29.0%" 같은 수치는
 * 진한 글씨로 둔다.
 */
function SummaryTile({
  label,
  value,
  caption,
  levelCaption,
}: {
  label: string;
  value: string;
  caption?: string | null;
  levelCaption?: string | null;
}) {
  return (
    <div className="min-w-0 flex-1 rounded-xl border border-border/70 bg-chip px-3 py-2.5">
      <p className="text-[11px] font-medium text-muted">{label}</p>
      <p className="mt-1 truncate text-[15px] font-bold leading-tight text-ink" title={value}>
        {value}
      </p>
      {levelCaption ? (
        <CongestionLevelChip level={levelCaption} className="mt-1.5" />
      ) : (
        caption && <p className="mt-1 truncate text-[11px] font-semibold text-label">{caption}</p>
      )}
    </div>
  );
}

/** 결제 금액 순위 뱃지. 1위만 채워 강조하고 나머지는 같은 계열의 옅은 배경을 쓴다. */
function RankBadge({ rank }: { rank: number }) {
  return (
    <span
      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
        rank === 1 ? "bg-brand text-white" : "bg-sky-light text-brand-deep"
      }`}
      aria-label={`${rank}위`}
    >
      {rank}
    </span>
  );
}

export function SeoulRealtimeSummarySection({ card }: { card: InfoPlaceCardData }) {
  if (!SUPPORTED_QUESTION_TYPES.has(card.question_type)) return null;
  const summary = card.seoul_realtime_summary;
  if (!summary) return null;

  const populationRange = formatPopulationRangeCompact(
    summary.population_min,
    summary.population_max,
  );
  const paymentRange = formatPaymentAmountRange(summary.payment_amount_min, summary.payment_amount_max);
  const topCategories = summary.top_payment_categories ?? [];

  const hasPopulation = Boolean(
    populationRange || summary.peak_forecast_hour_label || summary.top_age_label,
  );
  const hasCommercial = Boolean(summary.commercial_level || paymentRange || topCategories.length);
  if (!hasPopulation && !hasCommercial) return null;

  return (
    <>
      {hasPopulation && (
        <section className="border-t border-border px-4 py-3">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="text-sm font-bold text-ink">실시간 인구</h3>
            {card.population_observed_at && (
              <span className="text-[10px] text-muted">{card.population_observed_at} 기준</span>
            )}
          </div>
          <div className="mt-2 flex gap-2">
            {populationRange && (
              <SummaryTile
                label="현재 인구"
                value={populationRange}
                levelCaption={card.population_current_level}
              />
            )}
            {summary.peak_forecast_hour_label && (
              <SummaryTile
                // 서울시 앱의 "오늘의 인기 시간대"와 다르다 — 원본이 과거 추이를
                // 주지 않아 앞으로의 예측만 말할 수 있다.
                label="가장 붐빌 시간대"
                value={summary.peak_forecast_hour_label}
                levelCaption={summary.peak_forecast_level}
              />
            )}
            {summary.top_age_label && (
              <SummaryTile
                label="가장 많은 연령대"
                value={summary.top_age_label}
                caption={
                  summary.top_age_rate != null ? `${summary.top_age_rate.toFixed(1)}%` : null
                }
              />
            )}
          </div>
        </section>
      )}
      {hasCommercial && (
        <section className="border-t border-border px-4 py-3">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="text-sm font-bold text-ink">실시간 상권</h3>
            {summary.commercial_observed_at && (
              <span className="text-[10px] text-muted">{summary.commercial_observed_at} 기준</span>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-muted">신한카드 내국인 결제 기준 · 서울시 제공</p>
          <div className="mt-2 flex gap-2">
            {paymentRange && (
              <SummaryTile
                label="최근 10분 매출 총액"
                value={paymentRange}
                caption={
                  summary.payment_count != null ? `${summary.payment_count}건` : null
                }
              />
            )}
            {summary.commercial_level && (
              <div className="min-w-0 flex-1 rounded-xl border border-border/70 bg-chip px-3 py-2.5">
                <p className="text-[11px] font-medium text-muted">상권 활동</p>
                <CongestionLevelChip
                  level={summary.commercial_level}
                  size="md"
                  className="mt-1.5"
                />
              </div>
            )}
          </div>
          {topCategories.length > 0 && (
            <div className="mt-2">
              <p className="text-[11px] font-medium text-muted">
                최근 10분 매출 Top {topCategories.length} 업종
              </p>
              <ol className="mt-1.5 space-y-1.5">
                {topCategories.map((category, index) => {
                  const amount = formatPaymentAmountRange(
                    category.payment_amount_min,
                    category.payment_amount_max,
                  );
                  return (
                    <li
                      key={category.label}
                      className="flex items-center justify-between gap-2 rounded-lg bg-chip px-2.5 py-1.5 text-xs"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <RankBadge rank={index + 1} />
                        <span className="truncate font-semibold text-ink">{category.label}</span>
                      </span>
                      {amount ? (
                        <span className="shrink-0 font-bold text-label">{amount}</span>
                      ) : (
                        <CongestionLevelChip level={category.activity_level} />
                      )}
                    </li>
                  );
                })}
              </ol>
            </div>
          )}
        </section>
      )}
    </>
  );
}
