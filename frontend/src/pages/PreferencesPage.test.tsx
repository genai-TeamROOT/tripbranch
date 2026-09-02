/*
 * 역할: 취향 설정 화면의 선택 개수 제한(최소 3·최대 5)과 초기화·직접 입력을 검증한다.
 * 호출 시점: vitest 실행 시.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { AppShellProvider } from "../components/layout/AppShellContext";
import { loadPreferences } from "../state/preferenceStorage";
import { PreferencesPage } from "./PreferencesPage";
import { PREFERENCE_GROUPS } from "./preferenceOptions";

beforeEach(() => {
  localStorage.clear();
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

  // 결과를 보려고 사용자가 한 번 더 홈으로 이동하게 두지 않는다.
  expect(screen.getByTestId("probe")).toHaveTextContent("/");
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
