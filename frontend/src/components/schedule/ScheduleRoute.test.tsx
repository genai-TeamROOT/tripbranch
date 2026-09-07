/*
 * 역할: 정류장 카드 목록과 사진 연결, "다녀왔어요" 체크 켜고 끄기를 검증한다.
 *
 * 사진은 PlaceThumbnail 이 그린다 — 여기서 확인하는 것은 **일정 항목의 주소가 그
 * 컴포넌트까지 실제로 닿는지**다. 백엔드가 ScheduleItem.image_url 을 새로 내려보내게
 * 한 것이 이 화면을 위해서였으므로, 끊기면 그 작업 전체가 헛것이 된다.
 *
 * **체크의 저장·복원은 여기서 안 본다** — `useScheduleVisited.test.ts`가 잠근다.
 * 이 파일은 `visited`/`onToggleVisited`를 그냥 props로 받는다고 가정하고, 그
 * 값이 카드에 옳게 반영되는지만 본다(부모 역할은 작은 테스트용 컴포넌트가 한다).
 */

import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import type { ScheduleItem } from "../../types";
import { ScheduleRoute } from "./ScheduleRoute";

function stop(name: string, extra: Partial<ScheduleItem> = {}): ScheduleItem {
  return {
    order: 1,
    place_id: `p-${name}`,
    place_name: name,
    estimated_arrival: "14:10",
    estimated_duration_min: 90,
    travel_to_next_min: 6,
    travel_to_next_mode: "walking",
    travel_to_next_measured: true,
    reason: `${name}을 고른 이유입니다.`,
    ...extra,
  };
}

const ITEMS = [
  stop("국립현대미술관 서울", {
    image_url: "https://tong.visitkorea.or.kr/a.jpg",
    image_url_fallback: "https://tong.visitkorea.or.kr/a-big.jpg",
  }),
  stop("서울공예박물관", {
    estimated_arrival: "15:46",
    estimated_duration_min: 45,
    travel_to_next_min: 21,
    travel_to_next_mode: "transit",
    /* 실측이 아닌 구간 — 라벨에 "· 추정"이 붙는지 함께 본다. */
    travel_to_next_measured: false,
    image_url: "https://tong.visitkorea.or.kr/b.jpg",
  }),
  stop("광장시장", {
    estimated_arrival: "16:52",
    estimated_duration_min: 65,
    travel_to_next_min: null,
    travel_to_next_mode: null,
  }),
];

/* SchedulePage가 하는 역할(체크 상태를 들고 있다가 넘기는 것)을 흉내 낸다. */
function Harness({ initialVisited = new Set<number>() }: { initialVisited?: Set<number> }) {
  const [visited, setVisited] = useState(initialVisited);
  function toggle(index: number) {
    setVisited((previous) => {
      const next = new Set(previous);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }
  return <ScheduleRoute items={ITEMS} isEn={false} visited={visited} onToggleVisited={toggle} />;
}

function renderRoute(initialVisited?: Set<number>) {
  return render(
    <MemoryRouter>
      <Harness initialVisited={initialVisited} />
    </MemoryRouter>,
  );
}

test("일정 항목의 사진 주소가 화면까지 닿는다", () => {
  renderRoute();

  const sources = screen.getAllByRole("presentation", { hidden: true });
  const urls = sources.map((img) => img.getAttribute("src"));
  expect(urls).toContain("https://tong.visitkorea.or.kr/a.jpg");
  expect(urls).toContain("https://tong.visitkorea.or.kr/b.jpg");
});

test("사진이 없는 정류장은 자리표시를 그린다", () => {
  renderRoute();

  /* 광장시장에는 image_url 이 없다. 빈 칸을 두지 않고 같은 모양의 자리표시가 온다. */
  expect(screen.getAllByTestId("place-thumbnail-placeholder").length).toBe(1);
});

/*
 * 이동은 한 줄이다. 앞 정류장의 travel_to_next_min 을 뒤 카드 위에 적는다 —
 * 자기 카드의 값을 적으면 한 칸씩 밀린다.
 */
test("이동 한 줄이 앞 정류장 기준으로 붙는다", () => {
  renderRoute();

  expect(screen.getByText("도보 이동 6분")).toBeInTheDocument();
  /* 대중교통 구간은 실측 표시가 없으므로 "· 추정"이 붙는다. */
  expect(screen.getByText("대중교통 이동 21분 · 추정")).toBeInTheDocument();
});

test("마지막 정류장 뒤에는 이동 줄이 없다", () => {
  renderRoute();

  /* 광장시장의 travel_to_next_min 은 null 이다. */
  expect(screen.queryByText(/이동 약/)).not.toBeInTheDocument();
  expect(screen.getAllByText(/이동/).length).toBe(2);
});

test("visited로 넘긴 곳은 다녀왔어요로 뜬다", () => {
  renderRoute(new Set([0]));

  expect(screen.getByText("다녀왔어요")).toBeInTheDocument();
  // 다른 곳은 그대로 도착 시각을 보여준다.
  expect(screen.getByText("15:46 도착")).toBeInTheDocument();
});

test("체크하면 그 카드만 다녀왔어요로 바뀌고, 다시 누르면 되돌아간다", async () => {
  const user = userEvent.setup();
  renderRoute();

  expect(screen.queryByText("다녀왔어요")).not.toBeInTheDocument();

  const check = screen.getByRole("button", { name: "국립현대미술관 서울 다녀왔어요 체크" });
  await user.click(check);

  expect(screen.getByText("다녀왔어요")).toBeInTheDocument();

  const undo = screen.getByRole("button", { name: "국립현대미술관 서울 체크 되돌리기" });
  await user.click(undo);

  expect(screen.queryByText("다녀왔어요")).not.toBeInTheDocument();
  expect(screen.getByText("14:10 도착")).toBeInTheDocument();
});

test("정류장마다 순서와 무관하게 따로 체크할 수 있다", async () => {
  const user = userEvent.setup();
  renderRoute();

  await user.click(screen.getByRole("button", { name: "광장시장 다녀왔어요 체크" }));

  // 앞 두 곳은 광장시장(가장 뒤에 체크한 곳)보다 앞인데 안 체크했으니 건너뛴 것으로 본다.
  expect(screen.getAllByText("건너뛰었어요")).toHaveLength(2);
  expect(screen.getByText("다녀왔어요")).toBeInTheDocument();
});

/*
 * 시간 띠(ScheduleRibbon)에서 색 영역으로 건너뛴 곳을 표시하려던 시도가
 * 전부 "칸"처럼 보인다는 되돌림을 받아서(2026-09-07), 카드 쪽으로 옮겼다.
 * 정류장마다 이미 독립된 카드라 나눠 보이는 문제 자체가 없다.
 */
test("가장 뒤에 체크한 곳보다 앞인데 안 체크한 곳은 건너뛰었어요로 뜬다", () => {
  renderRoute(new Set([1]));

  // 첫 곳(인덱스 0)만 건너뛴 것 — 인덱스 1 자신은 체크됐고, 그 뒤는 아직 안 닿았다.
  expect(screen.getAllByText("건너뛰었어요")).toHaveLength(1);
  expect(screen.getByText("다녀왔어요")).toBeInTheDocument();
  // 세 번째(광장시장)는 아직 닿지 않은 것뿐이라 평범한 도착 시각을 보여준다.
  expect(screen.getByText("16:52 도착")).toBeInTheDocument();
});

test("건너뛴 카드의 체크 배지도 건너뛰었어요와 같은 색이다", () => {
  renderRoute(new Set([1]));

  const badge = screen
    .getByRole("button", { name: "국립현대미술관 서울 다녀왔어요 체크" })
    .querySelector("span");
  expect(badge).toHaveClass("bg-gold");
});
