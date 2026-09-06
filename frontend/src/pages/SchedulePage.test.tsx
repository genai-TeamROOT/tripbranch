/*
 * 역할: 일정 화면의 빈 상태(짠 일정 없음)를 검증한다.
 * 호출 시점: vitest 실행 시.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
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
    <AuthProvider>
      <MemoryRouter initialEntries={["/schedule"]}>
        <AppShellProvider>
          <TripProvider>
            <SchedulePage />
          </TripProvider>
        </AppShellProvider>
      </MemoryRouter>
    </AuthProvider>,
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
    <AuthProvider>
      <MemoryRouter initialEntries={["/schedule"]}>
        <AppShellProvider>
          <TripProvider>
            <SchedulePage />
          </TripProvider>
        </AppShellProvider>
      </MemoryRouter>
    </AuthProvider>,
  );

  /* 장소 이름은 두 곳에 나온다 — 시간 띠의 범례와 정류장 카드. 범례는 aria-hidden
     이라 소리로는 한 번만 읽히지만, 화면 질의에는 둘 다 걸린다. */
  expect(screen.getAllByText("역삼 아트뮤지엄").length).toBeGreaterThan(0);
  expect(screen.getAllByText("대림창고").length).toBeGreaterThan(0);
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
    <AuthProvider>
      <MemoryRouter initialEntries={[`/schedule?saved=${id}`]}>
        <AppShellProvider>
          <TripProvider>
            <SchedulePage />
          </TripProvider>
        </AppShellProvider>
      </MemoryRouter>
    </AuthProvider>,
  );
}

test("저장한 일정을 열면 그때 편성이 그대로 보인다", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(SAVED_DETAIL)));

  renderSaved(SAVED_DETAIL.id);

  expect((await screen.findAllByText("경복궁")).length).toBeGreaterThan(0);
  expect(screen.getByText("경복궁 한 바퀴")).toBeInTheDocument();
});

/*
 * 저장한 일정에는 시간 띠의 "지금"을 얹지 않는다.
 *
 * **시계를 고정해야 의미가 있는 테스트다.** 저장 일정은 14:30~16:00 인데, 그
 * 바깥 시각에 돌면 "지금"은 어차피 안 뜬다 — 그러면 이 테스트는 배선이 끊겨도
 * 통과한다(2026-09-06 되돌림 확인에서 실제로 그랬다). 일정 한가운데로 시계를
 * 맞춰, 넘기기만 하면 뜨는 상태에서 안 뜨는 것을 본다.
 */
test("저장한 일정에는 지금 표시가 뜨지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(SAVED_DETAIL)));
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(2026, 7, 31, 15, 15));

  try {
    renderSaved(SAVED_DETAIL.id);
    await screen.findAllByText("경복궁");

    expect(screen.queryByText("지금")).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
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

/*
 * 저장한 일정 목록을 사이드바에서 여기로 옮겼다(2026-09-04). **세 상태 모두**에
 * 있어야 한다 — 특히 "아직 짠 일정이 없어요"와 불러오기 실패 화면에서는 다른
 * 일정을 고를 유일한 입구다. 목록을 빼도 나머지 테스트는 전부 통과했다(되돌림 확인).
 */
test("저장한 일정 목록이 세 상태 모두에 있다", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ items: [] })));

  const heading = () => screen.getByRole("heading", { name: "저장한 일정" });

  // ① 짠 일정이 없을 때
  const empty = render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/schedule"]}>
        <AppShellProvider>
          <TripProvider>
            <SchedulePage />
          </TripProvider>
        </AppShellProvider>
      </MemoryRouter>
    </AuthProvider>,
  );
  expect(heading()).toBeInTheDocument();
  empty.unmount();

  // ② 짠 일정이 있을 때
  seedScheduleState();
  const filled = render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/schedule"]}>
        <AppShellProvider>
          <TripProvider>
            <SchedulePage />
          </TripProvider>
        </AppShellProvider>
      </MemoryRouter>
    </AuthProvider>,
  );
  expect(heading()).toBeInTheDocument();
  filled.unmount();

  // ③ 저장한 일정을 못 불러왔을 때
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) =>
      String(input).includes("/schedules/")
        ? new Response(null, { status: 404 })
        : Response.json({ items: [] }),
    ),
  );
  renderSaved("gone");
  expect(await screen.findByText("이미 지워졌거나 접근 권한이 없을 수 있어요.")).toBeInTheDocument();
  expect(heading()).toBeInTheDocument();
});
