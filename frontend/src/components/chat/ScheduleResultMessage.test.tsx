/*
 * 역할: 일정 카드의 "이 일정 저장" 동작을 검증한다. (SCHEDULE 카드 2)
 * 호출 시점: vitest 실행 시.
 *
 * **저장은 낙관적으로 그리지 않는다.** 보관함 담기와 달리 이건 목록에 새 줄을
 * 만드는 동작이라, 실패했는데 저장된 것처럼 보이면 사용자가 나중에 목록에서
 * 찾다가 없는 것을 겪는다. 그 규칙을 이 파일이 잠근다.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ScheduleResultMessage } from "./ScheduleResultMessage";
import type { ScheduleResult } from "../../types";

const saved: { calls: unknown[]; fails: boolean } = { calls: [], fails: false };

vi.mock("../../api/trip", () => ({
  saveSchedule: async (input: unknown) => {
    if (saved.fails) throw new Error("저장 실패");
    saved.calls.push(input);
    return { id: "sched-1" };
  },
}));

const SCHEDULE = {
  items: [
    {
      order: 1,
      place_id: "p1",
      place_name: "경복궁",
      estimated_arrival: "14:30",
      estimated_duration_min: 90,
      reason: "조용히 걷기 좋아요",
      travel_to_next_min: null,
      travel_to_next_mode: null,
      travel_to_next_measured: null,
      warnings: [],
    },
    {
      order: 2,
      place_id: "p2",
      place_name: "북촌한옥마을",
      estimated_arrival: "16:15",
      estimated_duration_min: 60,
      reason: "가까워요",
      travel_to_next_min: null,
      travel_to_next_mode: null,
      travel_to_next_measured: null,
      warnings: [],
    },
  ],
  total_duration_min: 165,
  route_summary: "종로 반나절",
  basis_note: "지금 기준",
  elapsed_ms: 1200,
} as unknown as ScheduleResult;

afterEach(() => {
  saved.calls = [];
  saved.fails = false;
});

function renderMessage() {
  return render(
    <ScheduleResultMessage
      schedule={SCHEDULE}
      isLoading={false}
      onRequestMore={() => {}}
      onRelaxRadius={() => {}}
      runId="run_1"
      sessionId="sess_1"
    />,
  );
}

test("저장하면 제목을 화면이 만들어 함께 보낸다", async () => {
  renderMessage();

  await userEvent.click(screen.getByRole("button", { name: "이 일정 저장" }));

  await waitFor(() => expect(saved.calls).toHaveLength(1));
  /* 서버는 payload를 열어보지 않기로 되어 있어 제목을 뽑을 수 없다 —
     일정을 그리고 있는 화면이 만든다. */
  expect(saved.calls[0]).toMatchObject({
    title: "경복궁 외 1곳",
    runId: "run_1",
    sessionId: "sess_1",
  });
});

test("저장하고 나면 버튼이 잠긴다", async () => {
  renderMessage();

  await userEvent.click(screen.getByRole("button", { name: "이 일정 저장" }));

  const done = await screen.findByRole("button", { name: "저장했어요" });
  expect(done).toBeDisabled();
});

/* 서버가 멱등이라 두 번 눌러도 목록은 한 줄이지만, 버튼이 계속 눌리면 사용자는
   "저장이 안 됐나" 싶어 계속 누른다. */
test("두 번 눌러도 요청은 한 번만 나간다", async () => {
  renderMessage();
  const button = screen.getByRole("button", { name: "이 일정 저장" });

  await userEvent.click(button);
  await screen.findByRole("button", { name: "저장했어요" });
  await userEvent.click(screen.getByRole("button", { name: "저장했어요" }));

  expect(saved.calls).toHaveLength(1);
});

test("저장에 실패하면 저장된 것처럼 보이지 않는다", async () => {
  saved.fails = true;
  renderMessage();

  await userEvent.click(screen.getByRole("button", { name: "이 일정 저장" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("저장하지 못했어요");
  /* 다시 누를 수 있어야 한다 — 잠긴 채로 두면 사용자가 할 수 있는 일이 없다. */
  expect(screen.getByRole("button", { name: "이 일정 저장" })).toBeEnabled();
});
