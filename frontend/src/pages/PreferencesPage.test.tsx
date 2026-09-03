/*
 * 역할: 취향 설정 화면의 선택 개수 제한(최소 3·최대 5)과 초기화·직접 입력을 검증한다.
 * 호출 시점: vitest 실행 시.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { AppShellProvider } from "../components/layout/AppShellContext";
import { loadPreferences } from "../state/preferenceStorage";
import { resetPreferenceSync } from "../state/preferenceSync";
import { PreferencesPage } from "./PreferencesPage";
import { PREFERENCE_GROUPS } from "./preferenceOptions";

/*
 * 계정 저장소를 인메모리로 흉내 낸다. 취향은 이제 이 기기와 계정 양쪽에 남고,
 * 저장이 계정까지 닿아야 화면이 홈으로 넘어간다 — 실제 fetch를 그대로 두면 매번
 * 실패 경로만 타서 성공 흐름을 한 번도 안 밟는다.
 */
const server = vi.hoisted(() => ({
  items: [] as { label: string; source: string; codes: readonly string[] }[],
  updatedAt: null as string | null,
  failNext: false,
  calls: 0,
}));

vi.mock("../api/trip", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/trip")>();
  return {
    ...actual,
    fetchPreferences: async () => ({ items: server.items, updated_at: server.updatedAt }),
    replacePreferences: async (items: { label: string; source: string; codes: readonly string[] }[]) => {
      server.calls += 1;
      if (server.failNext) throw new Error("네트워크 실패");
      server.items = [...items];
      server.updatedAt = "2026-09-03T00:00:00+09:00";
      return { items: server.items, updated_at: server.updatedAt };
    },
  };
});

beforeEach(() => {
  localStorage.clear();
  resetPreferenceSync();
  server.items = [];
  server.updatedAt = null;
  server.failNext = false;
  server.calls = 0;
});

/** 저장 뒤 어디로 갔는지 보려고 현재 경로를 화면에 흘려둔다. */
function LocationProbe() {
  return <span data-testid="probe">{useLocation().pathname}</span>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/preferences"]}>
      <AppShellProvider>
        <PreferencesPage />
        <LocationProbe />
      </AppShellProvider>
    </MemoryRouter>,
  );
}

test("3개 미만이면 저장 버튼이 남은 개수를 안내하며 비활성 상태다", async () => {
  const user = userEvent.setup();
  renderPage();

  const saveButton = screen.getByRole("button", { name: "3개 더 골라주세요" });
  expect(saveButton).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "조용한 곳" }));
  await user.click(screen.getByRole("button", { name: "카페" }));

  expect(screen.getByRole("button", { name: "1개 더 골라주세요" })).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "아이와 함께" }));

  const enabled = screen.getByRole("button", { name: "저장하기" });
  expect(enabled).not.toBeDisabled();
  expect(screen.getByText("3 / 5개 선택됨")).toBeInTheDocument();
});

test("6번째 칩은 선택되지 않고, 초기화하면 전부 풀린다", async () => {
  const user = userEvent.setup();
  renderPage();

  const options = ["조용한 곳", "아늑한 공간", "야경 명소", "사진 명소", "힐링하기 좋은"];
  for (const label of options) {
    await user.click(screen.getByRole("button", { name: label }));
  }
  expect(screen.getByText("5 / 5개 선택됨")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "넓고 쾌적한" }));
  expect(screen.getByText("5 / 5개 선택됨")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "넓고 쾌적한" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );

  await user.click(screen.getByRole("button", { name: "선택 초기화" }));
  expect(screen.getByText("0 / 5개 선택됨")).toBeInTheDocument();
});

test("키워드 직접 입력으로 새 칩을 추가하면 선택된 채로 나타난다", async () => {
  const user = userEvent.setup();
  renderPage();

  await user.click(screen.getByRole("button", { name: "키워드 직접 입력" }));
  await user.type(screen.getByPlaceholderText("예: 조용한 서점"), "조용한 서점");
  await user.click(screen.getByRole("button", { name: "추가" }));

  const chip = await screen.findByRole("button", { name: "조용한 서점" });
  expect(chip).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("1 / 5개 선택됨")).toBeInTheDocument();
});

/*
 * 이 화면의 칩은 예시 문구가 아니라 DB에 대응이 있는 것만 남긴 목록이다.
 * 근거 없는 문구가 다시 섞여 들어오는 것을 여기서 막는다 — 예전 목록에는
 * 대응이 0건인 칩이 5개 있었다(반려동물 동반·감성 인테리어·브런치 등).
 */
test("모든 칩이 대응하는 DB 코드를 하나 이상 갖는다", () => {
  const options = PREFERENCE_GROUPS.flat();
  expect(options.length).toBeGreaterThan(0);

  for (const option of options) {
    expect(option.codes.length, `${option.label}에 코드가 없다`).toBeGreaterThan(0);
    for (const code of option.codes) {
      expect(code.trim(), `${option.label}의 코드가 비었다`).not.toBe("");
    }
  }
});

test("칩 라벨이 축을 넘어 중복되지 않는다", () => {
  // 선택 상태를 label로 들고 있어서, 라벨이 겹치면 두 칩이 같이 눌린다.
  const labels = PREFERENCE_GROUPS.flat().map((option) => option.label);
  expect(new Set(labels).size).toBe(labels.length);
});

test("저장하면 이 기기에 남고, 다시 열면 고른 채로 시작한다", async () => {
  const user = userEvent.setup();
  const { unmount } = renderPage();

  for (const label of ["조용한 곳", "카페", "데이트 코스"]) {
    await user.click(screen.getByRole("button", { name: label }));
  }
  await user.click(screen.getByRole("button", { name: "저장하기" }));

  expect(loadPreferences()).toEqual([
    { label: "조용한 곳", source: "preference", codes: ["quiet"] },
    { label: "카페", source: "place_tag", codes: ["카페", "찻집"] },
    { label: "데이트 코스", source: "preference", codes: ["date"] },
  ]);

  unmount();
  renderPage();
  expect(screen.getByText("3 / 5개 선택됨")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "카페" })).toHaveAttribute("aria-pressed", "true");
});

test("직접 입력한 키워드는 custom으로 저장되고 다시 열어도 남는다", async () => {
  const user = userEvent.setup();
  const { unmount } = renderPage();

  await user.click(screen.getByRole("button", { name: "키워드 직접 입력" }));
  await user.type(screen.getByPlaceholderText("예: 조용한 서점"), "조용한 서점");
  await user.click(screen.getByRole("button", { name: "추가" }));
  for (const label of ["조용한 곳", "카페"]) {
    await user.click(screen.getByRole("button", { name: label }));
  }
  await user.click(screen.getByRole("button", { name: "저장하기" }));

  expect(loadPreferences()).toContainEqual({
    label: "조용한 서점",
    source: "custom",
    codes: [],
  });

  unmount();
  renderPage();
  expect(screen.getByRole("button", { name: "조용한 서점" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

/*
 * 저장 버튼은 3개 미만이면 눌리지 않아서 "다 빼고 저장"이라는 경로가 없다.
 * 초기화가 저장값까지 지우지 않으면 한번 저장한 취향을 되돌릴 방법이 사라진다.
 */
test("선택 초기화는 저장해 둔 값까지 지운다", async () => {
  const user = userEvent.setup();
  renderPage();

  for (const label of ["조용한 곳", "카페", "데이트 코스"]) {
    await user.click(screen.getByRole("button", { name: label }));
  }
  await user.click(screen.getByRole("button", { name: "저장하기" }));
  expect(loadPreferences()).toHaveLength(3);

  await user.click(screen.getByRole("button", { name: "선택 초기화" }));

  expect(loadPreferences()).toEqual([]);
  expect(screen.getByRole("status")).toHaveTextContent("저장해 둔 취향을 지웠어요");
});

test("저장하면 홈 화면으로 보낸다", async () => {
  const user = userEvent.setup();
  renderPage();

  expect(screen.getByTestId("probe")).toHaveTextContent("/preferences");
  for (const label of ["조용한 곳", "카페", "데이트 코스"]) {
    await user.click(screen.getByRole("button", { name: label }));
  }
  await user.click(screen.getByRole("button", { name: "저장하기" }));

  /* 계정까지 저장된 뒤에 넘어간다. 결과를 보려고 사용자가 한 번 더 홈으로
     이동하게 두지 않는다. */
  await waitFor(() => expect(screen.getByTestId("probe").textContent).toBe("/"));
});

/*
 * 저장 뒤 화면을 떠나므로 "추천엔 아직 반영되지 않는다"를 저장 안내로 띄울 수
 * 없다. 그래서 부제가 그 사실을 항상 들고 있어야 한다 — 빠지면 홈에 취향이
 * 뜬 것만 보고 추천이 달라졌다고 읽는다.
 */
test("부제가 추천에 아직 반영되지 않는다는 사실을 항상 밝힌다", () => {
  renderPage();

  expect(screen.getByText(/추천 결과에 반영하는 건 아직 준비 중이에요/)).toBeInTheDocument();
});


/* ------------------------------------------------------------ 계정 연결 */

test("저장하면 계정에도 올라간다", async () => {
  const user = userEvent.setup();
  renderPage();

  for (const label of ["조용한 곳", "카페", "데이트 코스"]) {
    await user.click(screen.getByRole("button", { name: label }));
  }
  await user.click(screen.getByRole("button", { name: "저장하기" }));

  await waitFor(() => expect(server.items.map((item) => item.label)).toEqual([
    "조용한 곳",
    "카페",
    "데이트 코스",
  ]));
});

/*
 * 이 파일에서 가장 중요한 테스트다. 계정에 못 올렸는데 조용히 넘어가면
 * 사용자는 다른 기기에서도 취향이 따라올 거라고 믿는다.
 */
test("계정에 저장하지 못하면 알리고 화면에 머문다", async () => {
  const user = userEvent.setup();
  server.failNext = true;
  renderPage();

  for (const label of ["조용한 곳", "카페", "데이트 코스"]) {
    await user.click(screen.getByRole("button", { name: label }));
  }
  await user.click(screen.getByRole("button", { name: "저장하기" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("계정에 저장하지 못했어요");
  expect(screen.getByTestId("probe").textContent).toBe("/preferences");
  /* 고른 값 자체는 잃지 않는다 — 이 기기에는 남아 있어야 한다. */
  expect(loadPreferences()).toHaveLength(3);
});

test("계정에 저장된 취향이 있으면 그 상태로 열린다", async () => {
  server.items = [
    { label: "조용한 곳", source: "preference", codes: ["quiet"] },
    { label: "카페", source: "place_tag", codes: ["카페", "찻집"] },
    { label: "야경 명소", source: "preference", codes: ["night_view"] },
  ];
  server.updatedAt = "2026-09-03T00:00:00+09:00";

  renderPage();

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "야경 명소" })).toHaveAttribute("aria-pressed", "true"),
  );
  expect(screen.getByText("3 / 5개 선택됨")).toBeInTheDocument();
});

/* 다른 기기에서 전부 해제한 사람의 계정은 "빈 목록"이 정본이다. 이 기기의 낡은
   값을 되살리면 안 된다. */
test("계정이 비어 있으면 이 기기 값을 계정으로 올린다", async () => {
  localStorage.setItem(
    "tb_preferences",
    JSON.stringify([{ label: "조용한 곳", source: "preference", codes: ["quiet"] }]),
  );

  renderPage();

  await waitFor(() => expect(server.items.map((item) => item.label)).toEqual(["조용한 곳"]));
});
