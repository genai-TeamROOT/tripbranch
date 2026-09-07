/*
 * 역할: 일정의 정류장들을 그린다. 지금 있는 곳은 크게, 나머지는 썸네일 카드로.
 * 입력: 일정 항목들, 언어, 지금 어디에 있는지.
 * 출력: 정류장 카드와 그 사이 이동 한 줄, 장소 상세 모달 열기.
 * 호출 시점: SchedulePage가 시간 띠 아래에 그린다.
 *
 * **모든 정류장을 같은 크기로 그리지 않는다.** 같으면 화면에 위계가 없어서 무엇을
 * 먼저 볼지가 정해지지 않는다. 이 앱은 갑자기 바뀐 일정을 다시 짜주는 앱이고, 그
 * 화면이 답할 첫 질문은 "지금 어디쯤인가"다 — 지금 있는 곳에만 큰 사진을 준다.
 *
 * 지금이 일정 밖이면(시작 전·끝난 뒤·저장한 일정) 첫 정류장을 크게 그린다. 그때는
 * "지금 여기" 표시 없이 도착 시각만 적는다.
 */

import { useState } from "react";
import { PlaceThumbnail } from "../PlaceThumbnail";
import { RecommendationDetailPreviewModal } from "../chat/RecommendationDetailPreviewModal";
import {
  SCHEDULE_CLUSTER_NOTE,
  SCHEDULE_CLUSTER_NOTE_EN,
  isSameCluster,
  scheduleTravelLabel,
} from "../../utils/scheduleTravel";
import type { ScheduleItem } from "../../types";

interface ScheduleRouteProps {
  items: ScheduleItem[];
  isEn: boolean;
  /** 지금 머물고 있는 정류장. 이동 중이거나 일정 밖이면 null. */
  nowIndex: number | null;
  /** 지금 있는 곳을 떠날 때까지 남은 분. */
  minutesLeftHere: number | null;
}

function travelLine(item: ScheduleItem, next: ScheduleItem | undefined, isEn: boolean): string | null {
  if (item.travel_to_next_min === null) return null;
  /* 묶인 구간이면 한마디 덧붙인다 (TP-243) — 체류가 짧게 잡힌 근거가 여기 있다. */
  const clustered = next !== undefined && isSameCluster(item, next);
  const base = isEn
    ? `${item.travel_to_next_min} min to next stop`
    : scheduleTravelLabel(
        item.travel_to_next_min,
        item.travel_to_next_mode,
        item.travel_to_next_measured,
      );
  if (!clustered) return base;
  return `${base} · ${isEn ? SCHEDULE_CLUSTER_NOTE_EN : SCHEDULE_CLUSTER_NOTE}`;
}

export function ScheduleRoute({ items, isEn, nowIndex, minutesLeftHere }: ScheduleRouteProps) {
  const [detailFor, setDetailFor] = useState<ScheduleItem | null>(null);

  /* 지금 있는 곳이 없으면 첫 곳을 크게 — 화면이 사진 없이 시작하지 않게 한다. */
  const heroIndex = nowIndex ?? 0;
  const hero = items[heroIndex];
  const rest = items.filter((_, index) => index !== heroIndex);

  return (
    <div className="flex flex-col gap-4">
      {/* 지금 있는 곳 */}
      <div className="relative overflow-hidden rounded-2xl">
        <PlaceThumbnail
          src={hero.image_url}
          fallbackSrc={hero.image_url_fallback}
          className="aspect-[16/10] w-full"
        />
        {/* 사진 위 글자를 읽히게 하는 기능적 그라디언트다. 장식이 아니다. */}
        <div className="absolute inset-0 bg-gradient-to-t from-ink-strong/85 via-ink-strong/45 to-transparent" />
        <button
          type="button"
          onClick={() => setDetailFor(hero)}
          className="absolute right-3 top-3 rounded-full bg-ink-strong/55 px-3 py-1.5 text-xs font-bold text-white backdrop-blur-sm"
        >
          {isEn ? "View place details" : "장소 상세보기"}
        </button>
        <div className="absolute inset-x-0 bottom-0 flex flex-col gap-1 p-4 text-white">
          {nowIndex !== null && minutesLeftHere !== null && (
            <span className="flex items-center gap-1.5 self-start rounded-full bg-white/20 px-2.5 py-1 text-[11px] font-bold tabular-nums backdrop-blur-sm">
              <span className="h-1.5 w-1.5 rounded-full bg-calm" aria-hidden />
              {isEn
                ? `Here now · leave in ${minutesLeftHere} min`
                : `지금 여기 · ${minutesLeftHere}분 뒤 출발`}
            </span>
          )}
          <h3 className="text-xl font-bold tracking-tight">{hero.place_name}</h3>
          <p className="max-w-[40ch] text-[13px] leading-relaxed text-white/85">{hero.reason}</p>
          <p className="mt-0.5 text-xs tabular-nums text-white/75">
            {isEn
              ? `Arrive ${hero.estimated_arrival} · stay ${hero.estimated_duration_min} min`
              : `${hero.estimated_arrival} 도착 · ${hero.estimated_duration_min}분 머무름`}
          </p>
          {hero.warnings != null && hero.warnings.length > 0 && (
            /* 경고 색은 기존 일정 화면과 같은 text-gold 다. 사진 위라 배경 없이도 읽힌다. */
            <p className="mt-1 text-[11px] leading-snug text-gold">{hero.warnings.join(" / ")}</p>
          )}
        </div>
      </div>

      {rest.length > 0 && (
        <div className="flex flex-col">
          <h4 className="mb-2 text-xs font-bold text-muted">{isEn ? "Next" : "다음"}</h4>
          {items.map((item, index) => {
            if (index === heroIndex) return null;
            const previous = items[index - 1];
            const leg = previous ? travelLine(previous, item, isEn) : null;
            return (
              <div key={item.place_id}>
                {/* 이동은 한 줄이다. 높이로 표현하면 죽은 공간이 되고, 길이 비교는
                    위의 시간 띠가 대신한다. */}
                {leg && (
                  <p className="relative py-2 pl-10 text-xs tabular-nums text-muted before:absolute before:bottom-0 before:left-[19px] before:top-0 before:w-0.5 before:bg-[repeating-linear-gradient(to_bottom,var(--color-border)_0_4px,transparent_4px_8px)]">
                    {leg}
                  </p>
                )}
                <div className="flex gap-3 rounded-2xl border border-border p-3">
                  <PlaceThumbnail
                    src={item.image_url}
                    fallbackSrc={item.image_url_fallback}
                    className="h-24 w-24 shrink-0 rounded-xl"
                  />
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-xs font-bold tabular-nums text-brand">
                      {isEn ? `Arrive ${item.estimated_arrival}` : `${item.estimated_arrival} 도착`}
                    </span>
                    <h3 className="truncate text-base font-bold tracking-tight text-ink">
                      {item.place_name}
                    </h3>
                    <p className="line-clamp-2 text-[13px] leading-snug text-muted">{item.reason}</p>
                    <span className="mt-auto text-xs tabular-nums text-label">
                      {isEn
                        ? `Stay ${item.estimated_duration_min} min`
                        : `${item.estimated_duration_min}분 머무름`}
                    </span>
                    {item.warnings != null && item.warnings.length > 0 && (
                      <p className="mt-1 text-[11px] leading-snug text-gold">
                        {item.warnings.join(" / ")}
                      </p>
                    )}
                    <button
                      type="button"
                      onClick={() => setDetailFor(item)}
                      className="mt-1 self-start text-xs font-bold text-brand"
                    >
                      {isEn ? "View place details" : "장소 상세보기"}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {detailFor && (
        <RecommendationDetailPreviewModal
          placeId={detailFor.place_id}
          placeName={detailFor.place_name}
          onClose={() => setDetailFor(null)}
        />
      )}
    </div>
  );
}
