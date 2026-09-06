/*
 * 역할: AppHeader의 햄버거·위치 pill을 검증한다.
 * 입력: location prop(utils/locationChip 모델), 셸 드로어 컨텍스트.
 * 출력: 헤더(햄버거)가 항상 있고 pill은 모델이 있을 때만 그려진다. 출발지와 검색
 *   기준이 다르면 둘 다 그려진다. pill을 누르면 위치 설정으로 이동한다.
 *   뒤로가기는 사이드바가 없는 좁은 폭에서만 그려진다.
 *
 * AppHeader는 useAppShell()로 드로어를 열기 때문에 Provider 밖에서 렌더하면
 * 던진다 — 모든 케이스를 AppShellProvider로 감싼다.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { buildLocationChipModel } from "../../utils/locationChip";
import { AppHeader } from "./AppHeader";
import { AppShellProvider } from "./AppShellContext";

/* AppShellContext는 값 타입을 export하지 않는다 — 테스트에 필요한 모양만 적는다. */
interface ShellValue {
  drawerOpen: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
}

/* 화면이 넘기는 것과 같은 경로로 모델을 만든다 — 손으로 지어내면 조립 규칙이
   바뀌어도 이 테스트는 그대로 통과한다. null이면 pill 자체가 없는 경우다. */
function chipFor(settings: { origin: string | null; center: string | null } | null) {
  return settings === null ? null : buildLocationChipModel(settings);
}

/*
 * 폭 분기는 matchMedia로 판정한다(useIsDesktopSidebar). jsdom에는 레이아웃이 없어
 * 실제 창 크기로는 바뀌지 않으므로, 여기서 응답을 직접 정한다.
 */
function setSidebarVisible(visible: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: visible,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderHeader(
  settings: { origin: string | null; center: string | null } | null,
  shell?: Partial<ShellValue>,
  extra?: { routes?: ReactNode; onBack?: () => void },
) {
  const value: ShellValue | undefined = shell
    ? { drawerOpen: false, openDrawer: vi.fn(), closeDrawer: vi.fn(), ...shell }
    : undefined;

  return render(
    <AppShellProvider value={value}>
      <MemoryRouter initialEntries={["/chat"]}>
        <AppHeader location={chipFor(settings)} onBack={extra?.onBack} />
        {extra?.routes}
      </MemoryRouter>
    </AppShellProvider>,
  );
}

test("위치 모델이 없어도 헤더(햄버거)는 그려진다", () => {
  renderHeader(null);

  expect(screen.getByRole("button", { name: "메뉴 열기" })).toBeInTheDocument();
  // "근처"는 라벨 문구에서 뺐다 — 모델이 없으면 pill 자체가 없다.
  expect(screen.queryByText(/근처/)).not.toBeInTheDocument();
});

test("위치 모델이 있으면 pill을 그린다", () => {
  renderHeader({ origin: null, center: "경복궁 근처" });

  expect(screen.getByText("경복궁 근처")).toBeInTheDocument();
});

test("출발지와 검색 기준이 다르면 둘 다 그린다", () => {
  /* 하나만 보여주면 카드의 이동시간을 어디서 쟀는지가 화면에서 사라진다(D-067). */
  renderHeader({ origin: "안국역", center: "광화문역" });

  expect(screen.getByText("안국역")).toBeInTheDocument();
  expect(screen.getByText("광화문역")).toBeInTheDocument();
  expect(
    screen.getByRole("button", {
      name: "위치 설정으로 이동 (안국역에서 출발, 광화문역 주변에서 검색)",
    }),
  ).toBeInTheDocument();
});

test("둘이 같은 곳이면 한 번만 그린다", () => {
  /* "안국역 → 안국역"은 같은 이름을 두 번 쓰는 것이라 읽는 사람이 얻는 게 없다. */
  renderHeader({ origin: "안국역", center: "안국역" });

  expect(screen.getAllByText("안국역")).toHaveLength(1);
});

test("햄버거를 누르면 셸 드로어를 연다", async () => {
  const user = userEvent.setup();
  const openDrawer = vi.fn();
  renderHeader(null, { openDrawer });

  await user.click(screen.getByRole("button", { name: "메뉴 열기" }));

  expect(openDrawer).toHaveBeenCalledOnce();
});

/*
 * pill은 단순 표시가 아니라 위치 설정으로 가는 입구다. 시트로 열기 위해
 * 현재 위치를 backgroundLocation으로 실어 보내는지까지 확인한다 —
 * 이게 빠지면 전체 페이지로 갈아치워져 대화가 사라진다.
 */
test("위치 pill을 누르면 위치 설정을 시트로 연다", async () => {
  const user = userEvent.setup();

  function LocationProbe() {
    const location = useLocation();
    const background = (location.state as { backgroundLocation?: { pathname: string } } | null)
      ?.backgroundLocation;
    return <div data-testid="probe">{background?.pathname ?? "no-background"}</div>;
  }

  renderHeader({ origin: null, center: "경복궁 근처" }, undefined, {
    routes: (
      <Routes>
        <Route path="/location" element={<LocationProbe />} />
        <Route path="*" element={null} />
      </Routes>
    ),
  });

  await user.click(
    screen.getByRole("button", {
      name: "위치 설정으로 이동 (현재 위치에서 출발, 경복궁 근처 주변에서 검색)",
    }),
  );

  expect(screen.getByTestId("probe")).toHaveTextContent("/chat");
});

/*
 * **뒤로가기는 사이드바가 없는 폭에서만 낸다**(2026-09-06).
 *
 * 사이드바가 상시 보이면 취향·위치·일정 어디서든 돌아갈 곳이 이미 화면 왼쪽에
 * 다 펼쳐져 있다 — 헤더의 화살표는 같은 일을 하는 두 번째 길이라, 자리만 차지하고
 * 어디로 가는지는 덜 알려준다.
 *
 * 두 폭을 짝으로 잠근다. 넓은 폭만 보면 버튼을 통째로 지워도 통과한다.
 */
test("사이드바가 없는 폭에서는 뒤로가기를 그린다", () => {
  setSidebarVisible(false);
  renderHeader(null, undefined, { onBack: vi.fn() });

  expect(screen.getByRole("button", { name: "뒤로가기" })).toBeInTheDocument();
});

test("사이드바가 보이는 폭에서는 뒤로가기를 그리지 않는다", () => {
  setSidebarVisible(true);
  renderHeader(null, undefined, { onBack: vi.fn() });

  expect(screen.queryByRole("button", { name: "뒤로가기" })).not.toBeInTheDocument();
});

test("누르면 넘겨받은 뒤로가기 동작을 부른다", async () => {
  setSidebarVisible(false);
  const onBack = vi.fn();
  renderHeader(null, undefined, { onBack });

  await userEvent.click(screen.getByRole("button", { name: "뒤로가기" }));

  expect(onBack).toHaveBeenCalledTimes(1);
});
