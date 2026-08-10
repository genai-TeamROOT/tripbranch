/*
 * 역할: 타임라인에서 정류장(ScheduleCard) 사이의 이동 구간을 표시한다.
 * 입력: 다음 장소까지 이동 시간(분).
 * 출력: 세로선이 이어지는 좁은 구간에 "도보 이동 약 N분" 텍스트.
 * 호출 시점: ScheduleResultMessage가 item.travel_to_next_min이 있는 항목
 *   뒤에(=마지막 항목이 아닐 때) 렌더링한다.
 */

interface ScheduleTravelSegmentProps {
  minutes: number;
}

export function ScheduleTravelSegment({ minutes }: ScheduleTravelSegmentProps) {
  return (
    <li className="flex gap-3">
      <div className="flex w-6 shrink-0 justify-center">
        <span className="h-4 w-0.5 bg-gray-300 dark:bg-gray-700" />
      </div>
      <p className="flex flex-1 items-center pb-2 text-xs text-gray-400 dark:text-gray-500">
        도보 이동 약 {minutes}분
      </p>
    </li>
  );
}
