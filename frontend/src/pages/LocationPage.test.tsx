/*
 * 역할: 위치 설정 화면의 장소 검색, "현재 위치 사용" 동작, 즐겨찾기 목록을 검증한다.
 * 입력: mocked navigator.geolocation, mocked searchPlaces().
 * 출력: 검색 결과 목록과 빈 결과 문구, 좌표 갱신, 실패 시 오류 문구,
 *   즐겨찾기 추가/삭제.
 * 호출 시점: vitest 실행 시.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppShellProvider } from "../components/layout/AppShellContext";
import { TripProvider } from "../state/TripContext";
import { LocationPage } from "./LocationPage";
import { searchPlaces } from "../api/trip";
import { loadSearchCenter, saveSearchCenter } from "../state/searchCenterStorage";

vi.mock("../api/trip", () => ({ searchPlaces: vi.fn() }));

const searchPlacesMock = vi.mocked(searchPlaces);

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
  searchPlacesMock.mockReset();
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

test("검색하면 찾은 장소의 이름과 주소를 목록으로 보여준다", async () => {
  const user = userEvent.setup();
  searchPlacesMock.mockResolvedValue({
    places: [
      {
        name: "안국역",
        address: "서울특별시 종로구 견지동",
        road_address: "서울특별시 종로구 율곡로 62",
        category: "교통,지하철",
        latitude: 37.5765389,
        longitude: 126.9856,
      },
    ],
    outside_service_area_count: 0,
  });
  renderPage();

  await user.type(screen.getByLabelText("장소 검색"), "안국역");
  await user.click(screen.getByRole("button", { name: "검색" }));

  expect(await screen.findByText("안국역")).toBeInTheDocument();
  expect(screen.getByText("서울특별시 종로구 율곡로 62")).toBeInTheDocument();
  expect(searchPlacesMock).toHaveBeenCalledWith("안국역");
});

test("검색 결과를 고르면 검색 위치로 잡히고, 해제하면 풀린다", async () => {
  const user = userEvent.setup();
  searchPlacesMock.mockResolvedValue({
    places: [
      {
        name: "안국역",
        address: "서울특별시 종로구 견지동",
        road_address: "서울특별시 종로구 율곡로 62",
        category: "교통,지하철",
        latitude: 37.5765389,
        longitude: 126.9856,
      },
    ],
    outside_service_area_count: 0,
  });
  renderPage();

  await user.type(screen.getByLabelText("장소 검색"), "안국역");
  await user.click(screen.getByRole("button", { name: "검색" }));
  await user.click(await screen.findByRole("button", { name: /안국역/ }));

  expect(screen.getByText("이 위치를 기준으로 찾아요")).toBeInTheDocument();
  // 고르고 나면 결과 목록은 닫힌다 — 이미 정했으니 계속 띄워 둘 이유가 없다.
  expect(screen.queryByText("검색 결과")).not.toBeInTheDocument();

  // 저장소가 진실이다 — 발화를 보낼 때 HomePage·ChatPage가 여기서 읽어 간다.
  expect(loadSearchCenter()).toBe("안국역");

  await user.click(screen.getByRole("button", { name: "해제" }));

  expect(screen.queryByText("이 위치를 기준으로 찾아요")).not.toBeInTheDocument();
  expect(loadSearchCenter()).toBeNull();
});

test("이전에 고른 검색 위치가 있으면 화면을 열자마자 보여준다", () => {
  saveSearchCenter("서울역");
  renderPage();

  expect(screen.getByText("이 위치를 기준으로 찾아요")).toBeInTheDocument();
  expect(screen.getByText("서울역")).toBeInTheDocument();
});

test("서울 밖 결과만 걸러졌으면 지역 제한을 알려준다", async () => {
  const user = userEvent.setup();
  searchPlacesMock.mockResolvedValue({ places: [], outside_service_area_count: 3 });
  renderPage();

  await user.type(screen.getByLabelText("장소 검색"), "해운대");
  await user.click(screen.getByRole("button", { name: "검색" }));

  expect(await screen.findByText("서울 지역만 검색할 수 있어요")).toBeInTheDocument();
  expect(screen.queryByText("찾은 장소가 없어요")).not.toBeInTheDocument();
});

test("서울 밖도 아니고 찾지도 못했으면 검색어 문제로 안내한다", async () => {
  const user = userEvent.setup();
  searchPlacesMock.mockResolvedValue({ places: [], outside_service_area_count: 0 });
  renderPage();

  await user.type(screen.getByLabelText("장소 검색"), "ㅁㄴㅇㄹ");
  await user.click(screen.getByRole("button", { name: "검색" }));

  expect(await screen.findByText("찾은 장소가 없어요")).toBeInTheDocument();
});

test("검색 전에는 결과 영역 자체를 보여주지 않는다", () => {
  renderPage();

  expect(screen.queryByText("검색 결과")).not.toBeInTheDocument();
  expect(screen.queryByText("찾은 장소가 없어요")).not.toBeInTheDocument();
});
