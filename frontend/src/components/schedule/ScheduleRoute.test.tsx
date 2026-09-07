/*
 * 역할: 정류장 목록의 위계(지금 있는 곳만 크게)와 사진 연결을 검증한다.
 *
 * 사진은 PlaceThumbnail 이 그린다 — 여기서 확인하는 것은 **일정 항목의 주소가 그
 * 컴포넌트까지 실제로 닿는지**다. 백엔드가 ScheduleItem.image_url 을 새로 내려보내게
 * 한 것이 이 화면을 위해서였으므로, 끊기면 그 작업 전체가 헛것이 된다.
 */

import { render, screen, within } from "@testing-library/react";
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

function renderRoute(nowIndex: number | null, minutesLeftHere: number | null = null) {
  return render(
    <MemoryRouter>
      <ScheduleRoute
        items={ITEMS}
        isEn={false}
        nowIndex={nowIndex}
        minutesLeftHere={minutesLeftHere}
      />
    </MemoryRouter>,
  );
}

test("일정 항목의 사진 주소가 화면까지 닿는다", () => {
  renderRoute(null);

  const sources = screen.getAllByRole("presentation", { hidden: true });
  const urls = sources.map((img) => img.getAttribute("src"));
  expect(urls).toContain("https://tong.visitkorea.or.kr/a.jpg");
  expect(urls).toContain("https://tong.visitkorea.or.kr/b.jpg");
});

test("사진이 없는 정류장은 자리표시를 그린다", () => {
  renderRoute(null);

  /* 광장시장에는 image_url 이 없다. 빈 칸을 두지 않고 같은 모양의 자리표시가 온다. */
  expect(screen.getAllByTestId("place-thumbnail-placeholder").length).toBe(1);
});

/*
 * 모든 정류장이 같은 크기면 화면에 위계가 없다. 지금 있는 곳만 큰 사진을 받는다.
 */
test("지금 있는 곳이 크게 나오고 지금 여기 표시가 붙는다", () => {
  renderRoute(1, 20);

  expect(screen.getByText("지금 여기 · 20분 뒤 출발")).toBeInTheDocument();
  /* 두 번째 정류장이 큰 자리로 올라갔으므로 "다음" 목록에는 나오지 않는다. */
  const next = screen.getByText("다음").parentElement!;
  expect(within(next).queryByText("서울공예박물관")).not.toBeInTheDocument();
  expect(within(next).getByText("국립현대미술관 서울")).toBeInTheDocument();
});

test("지금이 일정 밖이면 첫 곳을 크게 그리되 지금 여기는 안 붙인다", () => {
  renderRoute(null);

  expect(screen.queryByText(/지금 여기/)).not.toBeInTheDocument();
  const next = screen.getByText("다음").parentElement!;
  expect(within(next).queryByText("국립현대미술관 서울")).not.toBeInTheDocument();
});

/*
 * 이동은 한 줄이다. 앞 정류장의 travel_to_next_min 을 뒤 카드 위에 적는다 —
 * 자기 카드의 값을 적으면 한 칸씩 밀린다.
 */
test("이동 한 줄이 앞 정류장 기준으로 붙는다", () => {
  renderRoute(null);

  expect(screen.getByText("도보 이동 6분")).toBeInTheDocument();
  /* 대중교통 구간은 실측 표시가 없으므로 "· 추정"이 붙는다. */
  expect(screen.getByText("대중교통 이동 21분 · 추정")).toBeInTheDocument();
});

test("마지막 정류장 뒤에는 이동 줄이 없다", () => {
  renderRoute(null);

  /* 광장시장의 travel_to_next_min 은 null 이다. */
  expect(screen.queryByText(/이동 약/)).not.toBeInTheDocument();
  expect(screen.getAllByText(/이동/).length).toBe(2);
});

test("묶인 구간은 한국어와 영어 둘 다 이어서 둘러보라고 말한다", () => {
  /*
   * TP-243 — 화면이 묶음을 보여주는 자리다. 이중언어 화면이라(PR #367) 두
   * 언어를 함께 잠근다: 한쪽만 고치면 다른 언어에서 조용히 사라진다.
   */
  const clustered = [
    stop("국립현대미술관 서울", { cluster_id: 1, travel_to_next_min: 3 }),
    stop("국제갤러리", { cluster_id: 1, travel_to_next_min: 21, travel_to_next_mode: "transit" }),
    stop("광장시장", { cluster_id: null, travel_to_next_min: null, travel_to_next_mode: null }),
  ];

  const { unmount } = render(
    <MemoryRouter>
      <ScheduleRoute items={clustered} isEn={false} nowIndex={0} minutesLeftHere={null} />
    </MemoryRouter>,
  );
  expect(screen.getByText("도보 이동 3분 · 이어서 둘러보기")).toBeInTheDocument();
  /* 두 번째 구간은 묶음 밖이라 그냥 이동 줄이다. */
  expect(screen.getByText("대중교통 이동 21분")).toBeInTheDocument();
  unmount();

  render(
    <MemoryRouter>
      <ScheduleRoute items={clustered} isEn nowIndex={0} minutesLeftHere={null} />
    </MemoryRouter>,
  );
  expect(screen.getByText("3 min to next stop · nearby stop")).toBeInTheDocument();
});

test("묶음 번호가 없는 옛 일정은 그대로 그린다", () => {
  // 저장해 둔 일정에는 이 필드가 없다. 없으면 묶음 표시만 없어야 한다.
  render(
    <MemoryRouter>
      <ScheduleRoute items={ITEMS} isEn={false} nowIndex={0} minutesLeftHere={null} />
    </MemoryRouter>,
  );

  expect(screen.queryByText(/이어서 둘러보기/)).not.toBeInTheDocument();
});

test("묶인 정류장 카드에만 테두리 색이 붙는다", () => {
  /* TP-243 — 일정 화면에서도 묶음이 눈에 보여야 한다. 히어로(첫 정류장)를 뺀
     나머지 목록에서 묶인 자리만 색을 받는다. */
  const clustered = [
    stop("국립현대미술관 서울", { cluster_id: 1, travel_to_next_min: 3 }),
    stop("국제갤러리", { cluster_id: 1, travel_to_next_min: 21 }),
    stop("광장시장", { cluster_id: null, travel_to_next_min: null }),
  ];

  const { container } = render(
    <MemoryRouter>
      <ScheduleRoute items={clustered} isEn={false} nowIndex={0} minutesLeftHere={null} />
    </MemoryRouter>,
  );

  expect(container.querySelectorAll("[data-cluster-link]")).toHaveLength(1);
});
