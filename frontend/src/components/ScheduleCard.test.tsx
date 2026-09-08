/*
 * 역할: 일정 카드의 "장소 상세보기" 입구를 검증한다.
 * 호출 시점: vitest 실행 시.
 *
 * /schedule 페이지에는 이 입구가 있었고 채팅 안 카드에만 없었다
 * (ScheduleRoute.tsx의 `장소 상세보기` + RecommendationDetailPreviewModal).
 * 같은 일정을 두 화면이 다르게 다루면 사용자에게는 한쪽이 고장으로 보인다.
 *
 * **모달을 통째로 모킹한다.** 여기서 잠글 것은 "어느 항목의 값으로 여는가"
 * 하나이고, 모달 자체는 상세 조회·지도 링크·위치 훅을 들고 있어 그것까지
 * 끌고 오면 이 파일이 검증하려는 배선이 그 뒤로 숨는다
 * (PhotoSimilarResultMessage.test.tsx가 쓰는 것과 같은 방식).
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ScheduleCard } from "./ScheduleCard";
import type { ScheduleItem } from "../types";

vi.mock("./chat/RecommendationDetailPreviewModal", () => ({
  RecommendationDetailPreviewModal: ({
    placeId,
    placeName,
    onClose,
  }: {
    placeId?: string;
    placeName?: string;
    onClose: () => void;
  }) => (
    <div data-testid="detail-modal" data-place-id={placeId}>
      {placeName}
      <button type="button" onClick={onClose}>
        모달 닫기
      </button>
    </div>
  ),
}));

function item(overrides: Partial<ScheduleItem> = {}): ScheduleItem {
  return {
    order: 1,
    place_id: "p1",
    place_name: "경복궁",
    estimated_arrival: "14:30",
    estimated_duration_min: 90,
    reason: "조용히 걷기 좋아요",
    travel_to_next_min: null,
    travel_to_next_mode: null,
    travel_to_next_measured: null,
    warnings: [],
    ...overrides,
  } as unknown as ScheduleItem;
}

function renderCard(overrides: Partial<ScheduleItem> = {}) {
  return render(
    <ul>
      <ScheduleCard item={item(overrides)} isLast />
    </ul>,
  );
}

test("일정 카드에서 장소 상세를 열 수 있다", async () => {
  renderCard();

  expect(screen.queryByTestId("detail-modal")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "장소 상세보기" }));

  expect(screen.getByTestId("detail-modal")).toBeInTheDocument();
});

test("상세는 그 카드가 가리키는 장소로 연다", async () => {
  /* 항목이 여럿일 때 다른 카드의 장소가 열리면 사용자는 자기가 누른 곳이
     아닌 곳의 운영시간을 보고 일정을 판단한다. 이름만 보면 시드가 기본값과
     같아 통과하므로 place_id까지 함께 잠근다. */
  renderCard({ place_id: "p2", place_name: "북촌한옥마을" });

  await userEvent.click(screen.getByRole("button", { name: "장소 상세보기" }));

  const modal = screen.getByTestId("detail-modal");
  expect(modal).toHaveAttribute("data-place-id", "p2");
  expect(modal).toHaveTextContent("북촌한옥마을");
});

test("닫으면 상세가 사라진다", async () => {
  /* onClose가 상태를 되돌리지 않으면 한 번 연 뒤로 카드가 모달에 덮인 채
     남는다 — 목록의 다른 카드를 누를 수 없게 된다. */
  renderCard();

  await userEvent.click(screen.getByRole("button", { name: "장소 상세보기" }));
  await userEvent.click(screen.getByRole("button", { name: "모달 닫기" }));

  expect(screen.queryByTestId("detail-modal")).not.toBeInTheDocument();
});
