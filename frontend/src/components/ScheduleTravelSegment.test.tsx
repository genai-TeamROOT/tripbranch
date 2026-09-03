/*
 * 일정 타임라인 구간 표기. (TP-216)
 *
 * 예전에는 이 자리가 "도보 이동 약 N분"으로 고정돼 있었고, 편성이 긴 구간을
 * 대중교통으로 전환하기 시작하면서 4.3km 61분 구간이 화면에는 도보로 떴다.
 */

import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { scheduleTravelLabel } from "../utils/scheduleTravel";
import { ScheduleTravelSegment } from "./ScheduleTravelSegment";

test("실측 구간은 이동수단과 시간만 말한다", () => {
  expect(scheduleTravelLabel(20, "transit", true)).toBe("대중교통 이동 20분");
  expect(scheduleTravelLabel(9, "walking", true)).toBe("도보 이동 9분");
  expect(scheduleTravelLabel(14, "driving", true)).toBe("자동차 이동 14분");
});

test("추정 구간은 값을 보여주고 추정임을 밝힌다", () => {
  // 추천 카드와 규칙이 다르다 — 일정은 이동시간 없이 성립하지 않으므로 숨기지 않는다.
  expect(scheduleTravelLabel(33, "walking", false)).toBe("도보 이동 33분 · 추정");
});

test("이동수단을 모르는 구간은 수단을 말하지 않는다", () => {
  // 서버가 좌표를 못 구해 시간표 폴백값(15분)을 쓴 자리다.
  expect(scheduleTravelLabel(15, null, false)).toBe("이동 약 15분");
  expect(scheduleTravelLabel(15, undefined, undefined)).toBe("이동 약 15분");
});

test("추정 구간에만 설명 툴팁이 붙는다", () => {
  const { unmount } = render(
    <ul>
      <ScheduleTravelSegment minutes={33} mode="walking" measured={false} />
    </ul>,
  );
  expect(screen.getByText("도보 이동 33분 · 추정")).toHaveAttribute("title");
  unmount();

  render(
    <ul>
      <ScheduleTravelSegment minutes={20} mode="transit" measured />
    </ul>,
  );
  expect(screen.getByText("대중교통 이동 20분")).not.toHaveAttribute("title");
});
