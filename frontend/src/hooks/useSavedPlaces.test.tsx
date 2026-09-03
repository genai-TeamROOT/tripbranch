/*
 * 역할: useSavedPlaces의 서버 재조회(refresh)를 검증한다.
 * 입력: 저장본으로 심어둔 세션(session_id 유무·saved_places), 모킹한 fetchSavedPlaces.
 * 출력: 세션이 있을 때만 조회가 일어나고, 그 결과로 화면 상태가 갱신되는지,
 *   조회가 실패해도 직전 목록이 유지되는지 확인.
 * 호출 시점: vitest 실행 시.
 *
 * 상태는 storage의 saveState로 심는다 — TripProvider가 초기값 위에 저장본을 덮어
 * 복원하므로, Probe 컴포넌트가 마운트되기 전에 session_id가 이미 반영돼 있다
 * (SavedPlacesBar.test.tsx와 같은 패턴).
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import { TripProvider } from "../state/TripContext";
import type { TripState } from "../state/TripContext";
import { saveState } from "../state/storage";
import type { SavedPlaceItem } from "../types";
import { useSavedPlaces } from "./useSavedPlaces";

const fetchSavedPlaces = vi.fn();

vi.mock("../api/trip", () => ({
  fetchSavedPlaces: (...args: unknown[]) => fetchSavedPlaces(...args),
  savePlace: vi.fn(),
  removeSavedPlace: vi.fn(),
}));

function saved(placeId: string, name: string): SavedPlaceItem {
  return {
    place_id: placeId,
    name,
    saved_from_run_id: "run-1",
    saved_at: "2026-09-01T00:00:00+09:00",
  };
}

function seed(sessionId: string | null, items: SavedPlaceItem[]): void {
  saveState({
    language: "ko",
    user_input: "",
    interpreted_conditions: null,
    recommendations: [],
    unverified_recommendations: [],
    shown_place_ids: [],
    messages: [],
    auditTurns: [],
    phase: "ready",
    error: null,
    session_id: sessionId,
    restored_title: null,
    device_location: null,
    device_location_captured_at: null,
    device_location_snoozed_until: null,
    awaiting_clarification: false,
    saved_places: items,
    agentProgress: null,
    streamingIntent: null,
  } satisfies TripState);
}

/* 훅을 직접 부르는 최소 화면. 버튼을 눌러야 조회가 나가므로 마운트 부수효과와
   섞이지 않는다 — 페이지가 언제 부르는지와 무관하게 훅 자체를 잰다. */
function Probe() {
  const { savedPlaces, refresh } = useSavedPlaces();
  return (
    <div>
      <button type="button" onClick={() => void refresh()}>
        다시 읽기
      </button>
      <div data-testid="count">{savedPlaces.length}</div>
    </div>
  );
}

function renderProbe() {
  return render(
    <TripProvider>
      <Probe />
    </TripProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  fetchSavedPlaces.mockReset();
});

test("세션이 있으면 서버 목록으로 교체한다", async () => {
  seed("session-1", [saved("p1", "아키비스트 서촌")]);
  fetchSavedPlaces.mockResolvedValue({
    session_id: "session-1",
    items: [saved("p1", "아키비스트 서촌"), saved("p2", "통인시장")],
    changed: false,
  });

  renderProbe();
  await userEvent.click(screen.getByRole("button", { name: "다시 읽기" }));

  await waitFor(() => expect(fetchSavedPlaces).toHaveBeenCalledWith("session-1"));
  await waitFor(() => expect(screen.getByTestId("count")).toHaveTextContent("2"));
});

test("세션이 없으면 서버를 부르지 않는다", async () => {
  seed(null, []);

  renderProbe();
  await userEvent.click(screen.getByRole("button", { name: "다시 읽기" }));

  expect(fetchSavedPlaces).not.toHaveBeenCalled();
  expect(screen.getByTestId("count")).toHaveTextContent("0");
});

test("서버 조회가 실패해도 직전 목록을 그대로 보여준다", async () => {
  seed("session-1", [saved("p1", "아키비스트 서촌")]);
  fetchSavedPlaces.mockRejectedValue(new Error("network"));

  renderProbe();
  await userEvent.click(screen.getByRole("button", { name: "다시 읽기" }));

  await waitFor(() => expect(fetchSavedPlaces).toHaveBeenCalledWith("session-1"));
  expect(screen.getByTestId("count")).toHaveTextContent("1");
});
