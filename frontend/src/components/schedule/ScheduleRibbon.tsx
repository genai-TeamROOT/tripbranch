/*
 * 역할: 일정 전체를 가로 막대 하나로 보여준다. 칸의 너비가 곧 시간이다.
 * 입력: 일정 항목들, 언어, "지금"을 그릴지 여부.
 * 출력: 시작·종료 시각, 머무름/이동 칸, 지금 위치 표시.
 * 호출 시점: SchedulePage가 일정 본문 맨 위에 그린다.
 *
 * **왜 세로가 아니라 가로인가.** 처음 시안은 왼쪽에 66px 세로 시간 축을 세웠는데,
 * 매 행에서 그 폭을 빼앗겨 본문이 좁아졌고 이동 21분 구간이 88px짜리 빈칸이 됐다.
 * 정보가 아니라 죽은 공간이었다. 눕히면 오후 전체가 한 줄에 들어오고 본문은 폭을
 * 다 쓴다.
 *
 * 계산은 전부 utils/scheduleTimeline.ts 에 있다 — 자정을 넘는 일정과 "지금이 일정
 * 밖"인 경우가 섞여 있어 화면 없이 값으로 확인해야 했다.
 */

import {
  buildScheduleTimeline,
  clockLabel,
  locateNow,
  type NowPosition,
} from "../../utils/scheduleTimeline";
import type { ScheduleItem } from "../../types";

interface ScheduleRibbonProps {
  items: ScheduleItem[];
  isEn: boolean;
  /**
   * 지금 시각. **저장한 일정에는 넘기지 않는다** — 저장된 도착 시각은 저장 시점
   * 기준이라 오늘 시계를 얹으면 사흘 전 일정이 방금 짠 것처럼 보인다
   * (SchedulePage의 basisAt과 같은 이유).
   */
  now?: Date | null;
}

export function ScheduleRibbon({ items, isEn, now }: ScheduleRibbonProps) {
  const timeline = buildScheduleTimeline(items);
  /* 도착 시각을 못 읽으면 띠를 통째로 그리지 않는다. 한 칸만 0분으로 그리면
     나머지 폭이 전부 틀어져서, 틀린 그림보다 없는 편이 낫다. */
  if (timeline === null || timeline.totalMinutes <= 0) return null;

  const position: NowPosition | null = now ? locateNow(timeline, now) : null;

  return (
    <section className="flex flex-col gap-1.5" aria-label={isEn ? "Timeline" : "시간 흐름"}>
      <div className="flex justify-between text-xs tabular-nums text-muted">
        <span>{clockLabel(timeline.startMinutes, isEn)}</span>
        <span>{clockLabel(timeline.endMinutes, isEn)}</span>
      </div>

      <div className="relative flex h-8 gap-[3px]">
        {timeline.segments.map((segment, index) => {
          const isStay = segment.kind === "stay";
          return (
            <span
              key={`${segment.kind}-${index}`}
              /* flexGrow 로 비율을 준다 — 퍼센트로 계산하면 칸 사이 3px 간격 때문에
                 합이 100%를 넘어 마지막 칸이 잘린다. */
              style={{ flexGrow: segment.minutes, flexBasis: 0 }}
              className={`flex items-center justify-center overflow-hidden whitespace-nowrap rounded-md text-[11px] font-bold ${
                isStay ? "bg-brand text-white" : "bg-chip text-muted"
              }`}
            >
              {/* 좁은 칸에서는 글자가 잘리느니 비운다. 8분 이하는 폭이 글자를 못 담는다. */}
              {segment.minutes >= 9 ? `${segment.minutes}${isEn ? "m" : "분"}` : ""}
            </span>
          );
        })}

        {position && (
          <span
            /* 띠는 구간 합을 100%로 그리므로 ratio 도 같은 축의 값이다. */
            style={{ left: `${position.ratio * 100}%` }}
            className="pointer-events-none absolute -top-1 bottom-[-4px] w-0.5 rounded bg-ink"
          >
            <span className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-ink px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-white">
              {isEn ? "Now" : "지금"}
            </span>
          </span>
        )}
      </div>

      {/*
        칸 아래 이름. 이동 칸은 이름이 없으므로 앞 정류장 칸에 붙여 폭을 합친다.

        **읽어주지 않는다(aria-hidden).** 이 줄은 위 칸이 어느 장소인지 잇는 시각
        보조이고, 같은 이름이 바로 아래 정류장 카드에 다시 나온다 — 소리로 들으면
        장소 이름이 두 번씩 읽힌다.
      */}
      <div aria-hidden className="flex gap-[3px] text-[11px] text-muted">
        {items.map((item, index) => {
          const stay = Math.max(0, item.estimated_duration_min);
          const travel =
            index === items.length - 1 ? 0 : Math.max(0, item.travel_to_next_min ?? 0);
          return (
            <span
              key={item.place_id}
              style={{ flexGrow: stay + travel, flexBasis: 0 }}
              className="overflow-hidden text-ellipsis whitespace-nowrap"
            >
              {item.place_name}
            </span>
          );
        })}
      </div>
    </section>
  );
}
