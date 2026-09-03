/*
 * 역할: 일정 화면의 빈 상태(짠 일정 없음)를 검증한다.
 * 호출 시점: vitest 실행 시.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppShellProvider } from "../components/layout/AppShellContext";
import { TripProvider } from "../state/TripContext";
import { SchedulePage } from "./SchedulePage";

beforeEach(() => {
  sessionStorage.clear();
});

test("짠 일정이 없으면 채팅으로 돌아가자는 안내를 보여준다", async () => {
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/schedule"]}>
      <AppShellProvider>
        <TripProvider>
          <SchedulePage />
        </TripProvider>
      </AppShellProvider>
    </MemoryRouter>,
  );

  expect(screen.getByText("아직 짠 일정이 없어요.")).toBeInTheDocument();

  const cta = screen.getByRole("button", { name: "홈에서 일정 짜기" });
  await user.click(cta);
});

/* TripProvider는 sessionStorage(state/storage.ts)에서 복원한다 — APPEND_CHAT_TURN을
   온전히 재현하려면 AgentResponse 전체가 필요해 무거우니, 저장 형식을 직접
   심어 넣는다(isChatMessage의 schedule_result 분기가 요구하는 필드만 채움). */
function seedScheduleState() {
  sessionStorage.setItem(
    "tripbranch_state",
    JSON.stringify({
      version: 7,
      state: {
        language: "ko",
        user_input: "",
        interpreted_conditions: null,
        recommendations: [],
        unverified_recommendations: [],
        shown_place_ids: [],
        messages: [
          {
            id: "schedule-1",
            type: "schedule_result",
            elapsed_ms: 120,
            schedule: {
              items: [
                {
                  order: 1,
                  place_id: "place-1",
                  place_name: "역삼 아트뮤지엄",
                  estimated_arrival: "15:02",
                  estimated_duration_min: 60,
                  travel_to_next_min: 12,
                  travel_to_next_mode: "transit",
                  travel_to_next_measured: true,
                  reason: "실내라 비를 피하며 둘러보기 좋아요",
                },
                {
                  order: 2,
                  place_id: "place-2",
                  place_name: "대림창고",
                  estimated_arrival: "16:14",
                  estimated_duration_min: 45,
                  travel_to_next_min: null,
                  reason: "천장이 높아 사진 찍기 좋은 공간이에요",
                },
              ],
              total_duration_min: 105,
              route_summary: "역삼 아트뮤지엄을 둘러본 후 대림창고로 이동하는 동선이에요.",
              basis_note: "이 정보는 계산 당시 시각 기준이에요.",
              elapsed_ms: 120,
            },
          },
        ],
        auditTurns: [],
        phase: "ready",
        error: null,
        session_id: null,
        device_location: null,
        device_location_captured_at: null,
        device_location_snoozed_until: null,
        awaiting_clarification: false,
        saved_places: [],
        agentProgress: null,
        streamingIntent: null,
      },
    }),
  );
}

test("짠 일정이 있으면 정류장 타임라인과 피드백 토글을 보여준다", async () => {
  const user = userEvent.setup();
  seedScheduleState();
  render(
    <MemoryRouter initialEntries={["/schedule"]}>
      <AppShellProvider>
        <TripProvider>
          <SchedulePage />
        </TripProvider>
      </AppShellProvider>
    </MemoryRouter>,
  );

  expect(screen.getByText("역삼 아트뮤지엄")).toBeInTheDocument();
  expect(screen.getByText("대림창고")).toBeInTheDocument();
  // 서버가 내려준 이동수단을 그대로 쓴다 — 예전에는 전 구간을 도보로 고정 표기했다(TP-216).
  expect(screen.getByText("대중교통 이동 12분")).toBeInTheDocument();
  // 마지막 정류장은 다음 이동이 없다(travel_to_next_min === null) — 구간 표기는 한 줄뿐이다.
  expect(screen.queryAllByText(/이동 \d+분$/)).toHaveLength(1);

  const helpful = screen.getByRole("button", { name: "도움이 됐어요" });
  expect(helpful).toHaveAttribute("aria-pressed", "false");
  await user.click(helpful);
  expect(helpful).toHaveAttribute("aria-pressed", "true");
});
