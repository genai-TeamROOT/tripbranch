/*
 * 역할: 위치 설정 화면의 상태 표시와 "위치 다시 가져오기" 동작을 검증한다.
 * 입력: mocked navigator.geolocation.
 * 출력: 미확인/확인 상태 문구, 새로고침 성공 시 좌표 갱신, 실패 시 오류 문구.
 * 호출 시점: vitest 실행 시.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppShellProvider } from "../components/layout/AppShellContext";
import { TripProvider } from "../state/TripContext";
import { LocationPage } from "./LocationPage";

function renderPage() {
  render(
    <MemoryRouter>
      <AppShellProvider>
        <TripProvider>
          <LocationPage />
        </TripProvider>
      </AppShellProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  // 로컬 .env의 Codex 테스트 좌표가 이 테스트의 mocked navigator 응답을 가리지
  // 않게 한다(App.test.tsx와 같은 이유 — utils/geolocation.ts의 개발 전용 우회).
  vi.stubEnv("VITE_TEST_DEVICE_LOCATION", "");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("아직 위치를 가져오지 않았으면 미확인 문구를 보여준다", () => {
  renderPage();

  expect(screen.getByText("아직 위치를 가져오지 않았어요")).toBeInTheDocument();
});

test("위치 다시 가져오기를 누르면 새 좌표를 받아 화면에 반영한다", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("navigator", {
    geolocation: {
      getCurrentPosition: vi.fn((success: PositionCallback) =>
        success({
          coords: { latitude: 37.5, longitude: 127.0 },
          timestamp: Date.now(),
        } as GeolocationPosition),
      ),
    },
  });
  renderPage();

  await user.click(screen.getByRole("button", { name: "위치 다시 가져오기" }));

  expect(await screen.findByText("37.5,127")).toBeInTheDocument();
  // getLocationAgeMinutes는 최소 1분으로 올림한다(utils/locationRefresh.ts) —
  // 방금 받아온 위치도 "1분 전"으로 보인다.
  expect(screen.getByText("1분 전에 확인했어요")).toBeInTheDocument();
});

test("위치를 가져오지 못하면 오류 문구를 보여준다", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("navigator", {
    geolocation: {
      getCurrentPosition: vi.fn((_success: PositionCallback, error: PositionErrorCallback) =>
        error({
          code: 1,
          PERMISSION_DENIED: 1,
          POSITION_UNAVAILABLE: 2,
          TIMEOUT: 3,
          message: "denied",
        } as GeolocationPositionError),
      ),
    },
  });
  renderPage();

  await user.click(screen.getByRole("button", { name: "위치 다시 가져오기" }));

  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
});
