/*
 * 역할: 시간 띠가 비율대로 그려지고 "지금"이 옳은 때에만 뜨는지 검증한다.
 *
 * 폭은 flexGrow 로 준다 — jsdom 에는 레이아웃이 없어 실제 픽셀은 못 재지만,
 * 비율을 정하는 값 자체는 인라인 스타일에 남아 있어 확인할 수 있다.
 */

import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { ScheduleItem } from "../../types";
import { ScheduleRibbon } from "./ScheduleRibbon";

function stop(
  arrival: string,
  stay: number,
  travel: number | null,
  name: string,
): ScheduleItem {
  return {
    order: 1,
    place_id: `p-${name}`,
    place_name: name,
    estimated_arrival: arrival,
    estimated_duration_min: stay,
    travel_to_next_min: travel,
    reason: "",
  };
}

const AFTERNOON = [
  stop("14:10", 90, 6, "국립현대미술관 서울"),
  stop("15:46", 45, 21, "서울공예박물관"),
  stop("16:52", 65, null, "광장시장"),
];

function segments(): HTMLElement[] {
  /* 띠의 칸들은 시간 흐름 영역 안의 인라인 flexGrow 를 가진 span 이다. */
  const region = screen.getByLabelText("시간 흐름");
  return Array.from(region.querySelectorAll<HTMLElement>("span[style*='flex-grow']"));
}

test("칸의 비율이 실제 분과 같다", () => {
  render(<ScheduleRibbon items={AFTERNOON} isEn={false} />);

  /* 머무름 3칸 + 이동 2칸, 그리고 아래 이름 3칸. 앞 5개가 띠다. */
  const grow = segments()
    .slice(0, 5)
    .map((el) => el.style.flexGrow);
  expect(grow).toEqual(["90", "6", "45", "21", "65"]);
});

test("시작과 끝 시각을 적는다", () => {
  render(<ScheduleRibbon items={AFTERNOON} isEn={false} />);

  expect(screen.getByText(/2:10/)).toBeInTheDocument();
  /* 끝은 마지막 도착 16:52 + 65분 = 17:57 이다. */
  expect(screen.getByText(/5:57/)).toBeInTheDocument();
});

test("좁은 칸에는 글자를 넣지 않는다", () => {
  render(<ScheduleRibbon items={AFTERNOON} isEn={false} />);

  /* 6분 칸은 폭이 글자를 못 담는다 — 잘린 글자를 보여주느니 비운다. */
  expect(screen.queryByText("6분")).not.toBeInTheDocument();
  expect(screen.getByText("90분")).toBeInTheDocument();
  expect(screen.getByText("21분")).toBeInTheDocument();
});

/*
 * 저장한 일정에는 "지금"을 얹지 않는다. 저장된 도착 시각은 저장 시점 기준이라
 * 오늘 시계를 얹으면 사흘 전 일정이 방금 짠 것처럼 보인다.
 */
test("지금 시각을 안 넘기면 지금 표시가 없다", () => {
  render(<ScheduleRibbon items={AFTERNOON} isEn={false} />);

  expect(screen.queryByText("지금")).not.toBeInTheDocument();
});

test("일정 안의 시각을 넘기면 그 위치에 지금이 뜬다", () => {
  /* 15:20 — 시작 14:10 에서 70분 지났다. 전체 227분 중 30.8%. */
  render(
    <ScheduleRibbon items={AFTERNOON} isEn={false} now={new Date(2026, 8, 6, 15, 20)} />,
  );

  const now = screen.getByText("지금");
  const line = now.parentElement!;
  expect(Number.parseFloat(line.style.left)).toBeCloseTo((70 / 227) * 100, 1);
});

test("일정이 끝난 뒤에는 지금 표시가 없다", () => {
  /* 100%에 붙이면 아직 일정 중인 것처럼 보인다. */
  render(
    <ScheduleRibbon items={AFTERNOON} isEn={false} now={new Date(2026, 8, 6, 20, 0)} />,
  );

  expect(screen.queryByText("지금")).not.toBeInTheDocument();
});

test("도착 시각을 못 읽으면 띠를 통째로 그리지 않는다", () => {
  /* 한 칸만 0분으로 그리면 나머지 폭이 전부 틀어진다 — 틀린 그림보다 없는 편이 낫다. */
  const broken = [stop("어제 오후", 90, null, "어딘가")];
  const { container } = render(<ScheduleRibbon items={broken} isEn={false} />);

  expect(container).toBeEmptyDOMElement();
});

test("영어로 바꾸면 단위와 지금 표기가 영어가 된다", () => {
  render(<ScheduleRibbon items={AFTERNOON} isEn now={new Date(2026, 8, 6, 15, 20)} />);

  expect(screen.getByText("90m")).toBeInTheDocument();
  expect(screen.getByText("Now")).toBeInTheDocument();
});
