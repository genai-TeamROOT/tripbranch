/*
 * 역할: 일정의 정류장들을 카드 목록으로 그린다.
 * 입력: 일정 항목들, 언어, 이 일정을 구분하는 키.
 * 출력: 정류장 카드와 그 사이 이동 한 줄, 장소 상세 모달 열기, "다녀왔어요" 체크.
 * 호출 시점: SchedulePage가 시간 띠 아래에 그린다.
 *
 * **한때 "지금 있는 곳"만 사진을 크게 키워 보여줬다.** 전체 폭 사진 위에
 * 그라디언트·문구·버튼을 겹친 큰 카드와 96px 정사각 썸네일 카드 사이를
 * `layoutId` 공유 애니메이션으로 이으려 했는데, 두 카드의 내부 구조가 너무
 * 달라 배율 계산이 어긋나 체크할 때마다 카드가 통째로 안 보이는 사고가 두
 * 번 났다. 자리만 유지하는 페이드인으로 낮췄다가, 결국 그 위계 자체를
 * 접었다(2026-09-07) — 모든 정류장을 같은 카드로 그리고, 체크는 각 카드가
 * 독립적으로 켜고 끈다. "지금 어디쯤인가"는 체크 표시가 대신 말해준다.
 *
 * **체크 상태는 SchedulePage가 들고 있다**(2026-09-07). 시간 띠(ScheduleRibbon)도
 * 같은 체크를 보고 다시 그려야 해서, 저장·복원은 `useScheduleVisited` 훅으로
 * 옮기고 여기는 그 결과만 받는다.
 *
 * **건너뛴 곳 표시는 여기(카드)가 맡는다**(2026-09-07). 시간 띠에서 색 영역으로
 * 구분해 보려 했지만 시도할 때마다 "칸"처럼 보인다는 되돌림을 받았다 — 정류장
 * 마다 이미 독립된 카드인 이곳이 오히려 자연스럽다. 체크한 것 중 가장 뒤보다
 * 앞이면서 아직 체크 안 한 카드에 "건너뛰었어요"를 띄운다.
 *
 * **묶음 표시(TP-243)는 develop에서 이어받았다.** 원래는 히어로를 뺀 나머지
 * 목록에만 붙었는데(히어로는 카드가 아니라 제외해야 했다), 위계를 접어 모든
 * 정류장이 같은 카드가 된 지금은 그 예외가 필요 없다 — 묶인 자리면 전부 테두리
 * 색을 받고, 배지는 묶음이 시작되는 자리에 한 번만 붙는다.
 */

import { useState } from "react";
import { Check } from "lucide-react";
import { PlaceThumbnail } from "../PlaceThumbnail";
import { RecommendationDetailPreviewModal } from "../chat/RecommendationDetailPreviewModal";
import { scheduleTravelLabel } from "../../utils/scheduleTravel";
import { ScheduleClusterBadge } from "../ScheduleClusterBadge";
import type { ScheduleItem } from "../../types";

interface ScheduleRouteProps {
  items: ScheduleItem[];
  isEn: boolean;
  /** 체크한 정류장 인덱스 집합(`useScheduleVisited`). */
  visited: Set<number>;
  /** 정류장 체크를 켜고 끈다. */
  onToggleVisited: (index: number) => void;
}

function travelLine(item: ScheduleItem, isEn: boolean): string | null {
  if (item.travel_to_next_min === null) return null;
  if (isEn) {
    return `${item.travel_to_next_min} min to next stop`;
  }
  return scheduleTravelLabel(
    item.travel_to_next_min,
    item.travel_to_next_mode,
    item.travel_to_next_measured,
  );
}

/*
 * 이 자리에 묶음 배지를 붙일지, 붙이면 몇 곳짜리인지. (TP-243)
 *
 * **묶음마다 한 번만 그린다** — 구간마다 붙이면 세 곳이 묶였을 때 같은 말이 두 번
 * 반복된다(ScheduleClusterBadge 주석). 묶음이 시작되는 자리, 즉 그 번호가 처음
 * 나오는 자리만 배지를 받는다. 혼자 있는 번호(size 1)는 묶음이 아니다.
 */
function badgeSize(items: ScheduleItem[], index: number): number | null {
  const id = items[index].cluster_id;
  if (id == null) return null;
  const size = items.filter((item) => item.cluster_id === id).length;
  if (size < 2) return null;
  return items.findIndex((item) => item.cluster_id === id) === index ? size : null;
}

export function ScheduleRoute({ items, isEn, visited, onToggleVisited }: ScheduleRouteProps) {
  const [detailFor, setDetailFor] = useState<ScheduleItem | null>(null);
  const furthestVisited = visited.size > 0 ? Math.max(...visited) : -1;

  return (
    <div className="flex flex-col gap-2">
      {items.map((item, index) => {
        const isVisited = visited.has(index);
        const isSkipped = !isVisited && index < furthestVisited;
        const previous = items[index - 1];
        const leg = previous ? travelLine(previous, isEn) : null;
        const clusterSize = badgeSize(items, index);
        return (
          <div key={item.place_id}>
            {clusterSize !== null && (
              <div className="mb-1.5">
                <ScheduleClusterBadge count={clusterSize} isEn={isEn} />
              </div>
            )}
            {/* 이동은 한 줄이다. 높이로 표현하면 죽은 공간이 되고, 길이 비교는
                위의 시간 띠가 대신한다. */}
            {leg && (
              <p className="relative py-2 pl-10 text-xs tabular-nums text-muted before:absolute before:bottom-0 before:left-[19px] before:top-0 before:w-0.5 before:bg-[repeating-linear-gradient(to_bottom,var(--color-border)_0_4px,transparent_4px_8px)]">
                {leg}
              </p>
            )}
            {/* 묶인 자리는 테두리에 색을 준다(TP-243) — 배지가 말로 하는 것을
                테두리가 눈으로 보여준다. */}
            <div
              data-cluster-link={item.cluster_id != null ? "true" : undefined}
              className={`relative flex gap-3 rounded-2xl border bg-white p-3 shadow-resting transition-opacity ${
                item.cluster_id != null ? "border-brand/40" : "border-border"
              } ${isVisited ? "opacity-60" : ""}`}
            >
              {/* 이미지 전체가 체크 버튼이다 — 배지만 누르게 하면 손끝 크기에 비해
                  너무 좁다. 체크됐다는 표시(배지)는 눌러도 되는 자리 위에 얹는다. */}
              <button
                type="button"
                onClick={() => onToggleVisited(index)}
                aria-pressed={isVisited}
                aria-label={
                  isVisited
                    ? isEn
                      ? `Undo — ${item.place_name} not visited yet`
                      : `${item.place_name} 체크 되돌리기`
                    : isEn
                      ? `Mark ${item.place_name} as visited`
                      : `${item.place_name} 다녀왔어요 체크`
                }
                className="relative h-24 w-24 shrink-0"
              >
                <PlaceThumbnail
                  src={item.image_url}
                  fallbackSrc={item.image_url_fallback}
                  className="h-24 w-24 rounded-xl"
                />
                {/* 체크 전에도 체크 아이콘을 그린다(회색) — 아이콘이 체크된 뒤에만
                    나오면 처음 보는 사람은 누를 수 있는 곳인지 모른다. */}
                <span
                  className={`absolute -right-1.5 -top-1.5 flex h-6 w-6 items-center justify-center rounded-full border-2 transition-colors ${
                    isVisited
                      ? "border-white bg-calm text-white"
                      : isSkipped
                        ? "border-white bg-gold text-white"
                        : "border-border bg-white text-muted"
                  }`}
                >
                  <Check size={13} />
                </span>
              </button>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5 pr-20">
                <span
                  className={`text-xs font-bold tabular-nums ${
                    isVisited ? "text-muted" : isSkipped ? "text-gold" : "text-brand"
                  }`}
                >
                  {isVisited
                    ? isEn
                      ? "Been here"
                      : "다녀왔어요"
                    : isSkipped
                      ? isEn
                        ? "Skipped"
                        : "건너뛰었어요"
                      : isEn
                        ? `Arrive ${item.estimated_arrival}`
                        : `${item.estimated_arrival} 도착`}
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
              </div>
              {/* 카드 우측 상단에 둬서, 아래로 늘어지던 텍스트 칸이 사진 높이에
                  맞춰진다. */}
              <button
                type="button"
                onClick={() => setDetailFor(item)}
                className="absolute right-3 top-3 whitespace-nowrap text-xs font-bold text-brand"
              >
                {isEn ? "View place details" : "장소 상세보기"}
              </button>
            </div>
          </div>
        );
      })}

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
