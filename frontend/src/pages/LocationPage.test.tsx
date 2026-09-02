/*
 * 역할: 위치 설정 화면의 "현재 위치 사용" 동작과 즐겨찾기 목록을 검증한다.
 * 입력: mocked navigator.geolocation.
 * 출력: 좌표 갱신, 실패 시 오류 문구, 즐겨찾기 추가/삭제.
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
  localStorage.clear();
  // 로컬 .env의 Codex 테스트 좌표가 이 테스트의 mocked navigator 응답을 가리지
  // 않게 한다(App.test.tsx와 같은 이유 — utils/geolocation.ts의 개발 전용 우회).
  vi.stubEnv("VITE_TEST_DEVICE_LOCATION", "");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("현재 위치 사용을 누르면 새 좌표를 받아 화면에 반영한다", async () => {
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

  await user.click(screen.getByRole("button", { name: "현재 위치 사용" }));

  expect(await screen.findByText(/37.5,127/)).toBeInTheDocument();
  // getLocationAgeMinutes는 최소 1분으로 올림한다(utils/locationRefresh.ts) —
  // 방금 받아온 위치도 "1분 전"으로 보인다.
  expect(screen.getByText(/1분 전에 확인했어요/)).toBeInTheDocument();
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

  await user.click(screen.getByRole("button", { name: "현재 위치 사용" }));

  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
});

test("즐겨찾기가 없으면 안내 문구를, 추가하면 목록에 보여준다", async () => {
  const user = userEvent.setup();
  renderPage();

  expect(screen.getByText("등록된 즐겨찾기가 없어요")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "추가" }));
  await user.type(screen.getByPlaceholderText("예: 회사 (역삼동)"), "회사 (역삼동)");
  // 헤더의 "+ 추가"와 모달 제출 버튼이 같은 이름이라, 나중에 열린(=마지막) 쪽을 누른다.
  const addButtons = screen.getAllByRole("button", { name: "추가" });
  await user.click(addButtons[addButtons.length - 1]);

  expect(await screen.findByText("회사 (역삼동)")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "회사 (역삼동) 즐겨찾기 삭제" }));

  expect(screen.queryByText("회사 (역삼동)")).not.toBeInTheDocument();
  expect(screen.getByText("등록된 즐겨찾기가 없어요")).toBeInTheDocument();
});
