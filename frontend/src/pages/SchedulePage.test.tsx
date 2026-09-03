/*
 * 역할: 일정 화면의 빈 상태(짠 일정 없음)를 검증한다.
 * 호출 시점: vitest 실행 시.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppShellProvider } from "../components/layout/AppShellContext";
import { TripProvider } from "../state/TripContext";
import { SchedulePage } from "./SchedulePage";

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
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
      version: 6,
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

/*
 * 저장한 일정 열기. (SCHEDULE 카드 2)
 *
 * **이 화면을 재사용하는 이유**는 사이드바 "일정"이 이미 여기를 열기 때문이다.
 * 목록에서 고른 일정이 다른 모양으로 열리면 같은 것을 두 가지로 그리게 된다.
 */

const SAVED_DETAIL = {
  id: "11111111-2222-4333-8444-555555555555",
  title: "종로 반나절",
  session_id: "sess_1",
  created_at: "2026-08-31T14:30:00+09:00",
  updated_at: "2026-08-31T14:30:00+09:00",
  payload: {
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
    ],
    total_duration_min: 90,
    route_summary: "경복궁 한 바퀴",
    basis_note: "8월 31일 14:30 기준",
    elapsed_ms: 1200,
  },
};

function renderSaved(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/schedule?saved=${id}`]}>
      <AppShellProvider>
        <TripProvider>
          <SchedulePage />
        </TripProvider>
      </AppShellProvider>
    </MemoryRouter>,
  );
}

test("저장한 일정을 열면 그때 편성이 그대로 보인다", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(SAVED_DETAIL)));

  renderSaved(SAVED_DETAIL.id);

  expect(await screen.findByText("경복궁")).toBeInTheDocument();
  expect(screen.getByText("경복궁 한 바퀴")).toBeInTheDocument();
});

/*
 * **여기가 이 기능에서 제일 틀리기 쉬운 곳이다.** 도착 시각·이동 시간은 저장
 * 시점 값이라, 화면이 지금 시각을 얹으면 사흘 전 일정이 방금 짠 것처럼 보인다.
 */
test("저장한 일정에는 지금 시각이 아니라 저장한 시각을 밝힌다", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(SAVED_DETAIL)));

  renderSaved(SAVED_DETAIL.id);

  expect(await screen.findByText(/저장한 일정이에요/)).toBeInTheDocument();
  expect(screen.queryByText(/기준으로 짠 동선이에요/)).not.toBeInTheDocument();
});

test("저장한 일정을 못 불러오면 그 사실을 알린다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ error: { message: "not found" } }, { status: 404 })),
  );

  renderSaved(SAVED_DETAIL.id);

  expect(await screen.findByText(/불러오지 못했어요/)).toBeInTheDocument();
  /* "아직 짠 일정이 없어요"로 뭉뚱그리면 사용자는 저장이 안 된 줄 안다. */
  expect(screen.queryByText("아직 짠 일정이 없어요.")).not.toBeInTheDocument();
});
