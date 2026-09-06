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
import { resetSavedSchedulesCache, subscribeSavedSchedules } from "../../state/savedSchedules";
import type { ScheduleResult } from "../../types";

const saved: { calls: unknown[]; fails: boolean; deleted: string[] } = {
  calls: [],
  fails: false,
  deleted: [],
};

vi.mock("../../api/trip", () => ({
  saveSchedule: async (input: unknown) => {
    if (saved.fails) throw new Error("저장 실패");
    saved.calls.push(input);
    return { id: "sched-1" };
  },
  deleteSavedSchedule: async (id: string) => {
    if (saved.fails) throw new Error("해제 실패");
    saved.deleted.push(id);
    return { id, deleted: true };
  },
  fetchSavedSchedules: async () => ({ items: [] }),
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
  saved.deleted = [];
  saved.fails = false;
  resetSavedSchedulesCache();
});

function renderMessage() {
  return render(
    <ScheduleResultMessage
      schedule={SCHEDULE}
      runId="run_1"
      sessionId="sess_1"
    />,
  );
}

test("저장할 이름을 제목으로 미리 보여준다", () => {
  /* 눌러야 비로소 이름이 생기면 무엇으로 저장되는지 모른 채 누르게 된다.
     사이드바 목록에 들어갈 이름과 같은 값을 미리 보여준다. */
  renderMessage();

  expect(screen.getByRole("heading", { name: "경복궁 외 1곳" })).toBeInTheDocument();
});

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

test("저장하고 나면 해제 버튼으로 바뀐다", async () => {
  renderMessage();

  await userEvent.click(screen.getByRole("button", { name: "이 일정 저장" }));

  /* 같은 자리에서 오가는 토글이라 잠그지 않는다 — 잠그면 되돌릴 길이 없다. */
  const toggle = await screen.findByRole("button", { name: "저장 해제" });
  expect(toggle).toBeEnabled();
  expect(toggle).toHaveAttribute("aria-pressed", "true");
});

test("저장했다고 잠깐 알린다", async () => {
  renderMessage();

  await userEvent.click(screen.getByRole("button", { name: "이 일정 저장" }));

  /* 아이콘 색만으로는 저장됐는지 알아채기 어려워 말로도 알린다. */
  expect(await screen.findByRole("status")).toHaveTextContent("저장했어요");
});

test("다시 누르면 저장을 해제한다", async () => {
  renderMessage();

  await userEvent.click(screen.getByRole("button", { name: "이 일정 저장" }));
  await userEvent.click(await screen.findByRole("button", { name: "저장 해제" }));

  await waitFor(() => expect(saved.deleted).toEqual(["sched-1"]));
  /* 해제하면 다시 저장할 수 있는 상태로 돌아온다. */
  expect(await screen.findByRole("button", { name: "이 일정 저장" })).toBeEnabled();
});

test("저장에 실패하면 저장된 것처럼 보이지 않는다", async () => {
  saved.fails = true;
  renderMessage();

  await userEvent.click(screen.getByRole("button", { name: "이 일정 저장" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("저장하지 못했어요");
  /* 다시 누를 수 있어야 한다 — 잠긴 채로 두면 사용자가 할 수 있는 일이 없다. */
  expect(screen.getByRole("button", { name: "이 일정 저장" })).toBeEnabled();
});

/*
 * 저장하면 사이드바 목록이 바로 바뀌어야 한다. 새로고침해야 보이면 사용자는
 * 저장이 안 된 줄 안다 — 실제로 그랬다(브라우저 검증 2026-09-03).
 */
test("저장하면 목록을 다시 받아온다", async () => {
  const seen: unknown[] = [];
  const unsubscribe = subscribeSavedSchedules((entries) => seen.push(entries));
  renderMessage();

  await userEvent.click(screen.getByRole("button", { name: "이 일정 저장" }));

  await waitFor(() => expect(seen).toHaveLength(1));
  unsubscribe();
});
