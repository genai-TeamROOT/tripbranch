/*
 * 역할: 저장한 일정 목록의 열기·이름 바꾸기·삭제를 잠근다.
 *
 * **원래 `SideDrawerContent.test.tsx`에 있던 테스트를 옮긴 것이다**(2026-09-04).
 * 목록이 사이드바에서 일정 화면으로 옮겨갔으므로 테스트도 함께 왔다.
 *
 * 저쪽은 `<App/>`을 통째로 띄우는 하네스였는데(사이드바가 앱 셸 안에만 있어서),
 * 이 컴포넌트는 자기 데이터를 직접 받아오므로 컴포넌트만 띄운다 — 대화 목록·
 * 즐겨찾기·로그아웃을 함께 세울 이유가 없다.
 *
 * 옮기면서 **테스트 하나를 지웠다**: "대화와 저장한 일정의 id가 겹쳐도 메뉴는
 * 하나만 뜬다". 그것은 두 목록이 메뉴 상태를 한 벌로 나눠 쓰며 `{ kind, id }`로
 * 구분할 때만 성립하던 가드다. 목록이 분리돼 각자 자기 id만 들게 됐으므로 겹칠
 * 대상 자체가 없어졌다.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { AuthProvider } from "../../auth/AuthContext";
import { TripProvider } from "../../state/TripContext";
import {
  refreshSavedSchedules,
  resetSavedSchedulesCache,
} from "../../state/savedSchedules";
import { GUEST_SESSION, resetSupabaseMock, setMockSession } from "../../test/supabaseMock";
import { resetSupabaseClient } from "../../auth/supabaseClient";
import { SavedScheduleList } from "./SavedScheduleList";

const server = vi.hoisted(() => ({
  schedules: [] as {
    id: string;
    title: string;
    session_id: string | null;
    created_at: string;
    updated_at: string;
  }[],
  renamed: [] as { id: string; title: string }[],
  deleted: [] as string[],
}));

vi.mock("../../api/trip", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/trip")>();
  return {
    ...actual,
    fetchSavedSchedules: async () => ({ items: server.schedules }),
    renameSavedSchedule: async (scheduleId: string, title: string) => {
      server.renamed.push({ id: scheduleId, title });
      server.schedules = server.schedules.map((item) =>
        item.id === scheduleId ? { ...item, title } : item,
      );
      return { ...server.schedules[0], title };
    },
    deleteSavedSchedule: async (scheduleId: string) => {
      server.deleted.push(scheduleId);
      server.schedules = server.schedules.filter((item) => item.id !== scheduleId);
      return { id: scheduleId, deleted: true };
    },
  };
});

const SEED = [
  {
    id: "sched-1",
    title: "종로 반나절",
    session_id: "chat-1",
    created_at: "2026-08-31T14:30:00+09:00",
    updated_at: "2026-08-31T14:30:00+09:00",
  },
  {
    id: "sched-2",
    title: "성수 저녁 코스",
    session_id: "chat-2",
    created_at: "2026-09-01T18:00:00+09:00",
    updated_at: "2026-09-01T18:00:00+09:00",
  },
];

beforeEach(() => {
  localStorage.clear();
  server.schedules = [];
  server.renamed = [];
  server.deleted = [];
  resetSavedSchedulesCache();
  resetSupabaseMock();
  resetSupabaseClient();
  setMockSession(GUEST_SESSION);
});

/* MemoryRouter는 window.location을 건드리지 않는다(원본 테스트는 <App/>과 실제
   라우터를 썼다). 이동 결과를 보려면 라우터 안에서 위치를 읽어 내보내야 한다. */
function LocationProbe() {
  return <output data-testid="search">{useLocation().search}</output>;
}

function renderList() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/schedule"]}>
        <TripProvider>
          <SavedScheduleList />
          <LocationProbe />
        </TripProvider>
      </MemoryRouter>
    </AuthProvider>,
  );
}

test("저장한 일정이 없으면 그 사실을 알린다", async () => {
  renderList();

  expect(await screen.findByText("아직 저장한 일정이 없어요")).toBeInTheDocument();
});

test("저장한 일정이 목록에 뜨고 누르면 그 일정이 열린다", async () => {
  server.schedules = [SEED[0]];
  renderList();

  /* 한 줄에 "열기"와 "메뉴" 두 버튼이 있다 — 정규식으로 찾으면 둘 다 걸린다. */
  const entry = await screen.findByRole("button", { name: "종로 반나절 일정 열기" });
  await userEvent.click(entry);

  /* SchedulePage가 ?saved=로 받아 같은 화면에서 갈아 끼운다. */
  await waitFor(() =>
    expect(screen.getByTestId("search").textContent).toContain("saved=sched-1"),
  );
});

test("저장한 일정 이름을 바꾸면 새 이름이 남는다", async () => {
  server.schedules = [...SEED];
  const user = userEvent.setup();
  renderList();

  await user.click(await screen.findByRole("button", { name: "종로 반나절 메뉴" }));
  await user.click(screen.getByRole("menuitem", { name: "이름 바꾸기" }));
  const input = screen.getByRole("textbox", { name: "일정 이름" });
  await user.clear(input);
  await user.type(input, "종로 반나절 (수정){Enter}");

  await waitFor(() =>
    expect(server.renamed).toEqual([{ id: "sched-1", title: "종로 반나절 (수정)" }]),
  );
  expect(await screen.findByText("종로 반나절 (수정)")).toBeInTheDocument();
});

test("저장한 일정을 삭제하면 목록에서 빠진다", async () => {
  server.schedules = [...SEED];
  const user = userEvent.setup();
  renderList();

  await user.click(await screen.findByRole("button", { name: "성수 저녁 코스 메뉴" }));
  await user.click(screen.getByRole("menuitem", { name: "삭제" }));

  await waitFor(() => expect(server.deleted).toEqual(["sched-2"]));
  await waitFor(() => expect(screen.queryByText("성수 저녁 코스")).not.toBeInTheDocument());
  // 다른 줄은 그대로 있다.
  expect(screen.getByText("종로 반나절")).toBeInTheDocument();
});

/* 대화 목록과 별도 저장소다. 세션이 30일 뒤 정리돼도 저장한 일정은 남는다 —
   사이드바에 있을 때는 "대화가 없어도 보인다"로 잠갔던 것을, 목록이 분리된 뒤에는
   대화와 무관하다는 사실 자체로 잠근다(대화 목록을 세우지 않고도 그려진다). */
test("대화 목록 없이도 저장한 일정만으로 그려진다", async () => {
  server.schedules = [{ ...SEED[0], session_id: null }];
  renderList();

  const list = await screen.findByRole("list");
  expect(within(list).getByText("종로 반나절")).toBeInTheDocument();
});

/*
 * 일정을 저장하면 목록이 **바로** 바뀌어야 한다. 새로고침해야 보이면 사용자는
 * 저장이 안 된 줄 안다(`savedSchedules.refreshSavedSchedules` 주석).
 *
 * 발신 측(저장 뒤 refresh를 부르는 것)은 `ScheduleResultMessage.test.tsx`가
 * 잠갔다. 여기서는 **수신 측** — 이 컴포넌트가 그 알림을 받아 다시 그리는지를
 * 본다. 구독을 끊어도 다른 테스트는 전부 통과했다(2026-09-04 되돌림 확인).
 */
test("목록이 갱신되면 다시 그린다", async () => {
  server.schedules = [SEED[0]];
  renderList();
  expect(await screen.findByText("종로 반나절")).toBeInTheDocument();

  server.schedules = [...SEED];
  await act(async () => {
    await refreshSavedSchedules();
  });

  expect(await screen.findByText("성수 저녁 코스")).toBeInTheDocument();
});
