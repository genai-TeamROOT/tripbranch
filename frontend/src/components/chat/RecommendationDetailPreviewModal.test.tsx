/*
 * 역할: 상세 모달의 사진 영역이 여러 장·한 장·없음 세 경우를 각각 어떻게 그리는지 검증한다.
 *
 * 사진 목록(place_image_embeddings)이 있는 장소는 전체의 30%뿐이라, 나머지에서
 * 대표 이미지 한 장이 그대로 나오는지가 갤러리 자체만큼 중요하다.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { fetchRecommendationPlaceDetails } from "../../api/trip";
import { TripProvider } from "../../state/TripContext";
import type { InfoPlaceCard } from "../../types";
import { RecommendationDetailPreviewModal } from "./RecommendationDetailPreviewModal";

vi.mock("../../api/trip", () => ({
  fetchRecommendationPlaceDetails: vi.fn(),
}));

vi.mock("../../utils/naverDirections", () => ({
  openNaverMapSearch: vi.fn(),
  openNaverDirections: vi.fn(),
}));

const mockedFetch = vi.mocked(fetchRecommendationPlaceDetails);

function card(overrides: Partial<InfoPlaceCard> = {}): InfoPlaceCard {
  return {
    question_type: "general_info",
    answer_fields: {},
    place_id: "126508",
    place_name: "경복궁",
    latitude: null,
    longitude: null,
    thumbnail_url: "https://example.test/gyeongbokgung.jpg",
    overview: "조선 왕조의 법궁이다.",
    operating_hours: "09:00~18:00",
    rest_date: null,
    parking: null,
    parking_fee: null,
    fee: null,
    baby_carriage: null,
    pet: null,
    credit_card: null,
    restroom: null,
    homepage: null,
    ...overrides,
  };
}

/** 모달은 열리자마자 상세를 보강 조회한다. 조회 결과가 화면에 그려지는 값이다. */
function renderModal(resolved: InfoPlaceCard) {
  mockedFetch.mockResolvedValue({
    status: "success",
    requested_place_id: resolved.place_id,
    place_card: resolved,
  });
  return render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );
}

beforeEach(() => {
  mockedFetch.mockReset();
});

it("사진이 여러 장이면 첫 장을 크게 보여주고 나머지를 목록으로 준다", async () => {
  renderModal(
    card({
      photos: [
        { url: "https://tong.visitkorea.or.kr/126508-1.jpg", image_name: "경복궁 (1)" },
        { url: "https://tong.visitkorea.or.kr/126508-2.jpg", image_name: null },
        { url: "https://tong.visitkorea.or.kr/126508-3.jpg", image_name: null },
      ],
    }),
  );

  const main = await screen.findByRole("img", { name: "경복궁 사진 1번째" });
  expect(main).toHaveAttribute("src", "https://tong.visitkorea.or.kr/126508-1.jpg");
  expect(screen.getByText("1 / 3")).toBeInTheDocument();

  const list = screen.getByRole("group", { name: "경복궁 사진 목록" });
  expect(within(list).getAllByRole("button")).toHaveLength(3);
});

it("목록에서 고른 사진이 큰 사진으로 바뀐다", async () => {
  const user = userEvent.setup();
  renderModal(
    card({
      photos: [
        { url: "https://tong.visitkorea.or.kr/126508-1.jpg", image_name: null },
        { url: "https://tong.visitkorea.or.kr/126508-2.jpg", image_name: null },
      ],
    }),
  );

  await screen.findByRole("img", { name: "경복궁 사진 1번째" });
  await user.click(screen.getByRole("button", { name: "경복궁 사진 2번째 보기" }));

  const main = screen.getByRole("img", { name: "경복궁 사진 2번째" });
  expect(main).toHaveAttribute("src", "https://tong.visitkorea.or.kr/126508-2.jpg");
  expect(screen.getByText("2 / 2")).toBeInTheDocument();
});

it("사진 목록이 비면 대표 이미지 한 장을 그대로 보여준다", async () => {
  renderModal(card({ photos: [] }));

  const image = await screen.findByRole("img", { name: "경복궁 이미지" });
  expect(image).toHaveAttribute("src", "https://example.test/gyeongbokgung.jpg");
  // 한 장뿐이면 고를 것이 없으므로 목록과 장수 표시를 만들지 않는다.
  expect(screen.queryByRole("group", { name: "경복궁 사진 목록" })).not.toBeInTheDocument();
  expect(screen.queryByText("1 / 1")).not.toBeInTheDocument();
});

it("닫기 버튼을 누르면 슬라이드다운이 끝난 뒤 onClose를 부른다", async () => {
  const user = userEvent.setup();
  const onClose = vi.fn();
  mockedFetch.mockResolvedValue({
    status: "success",
    requested_place_id: "126508",
    place_card: card(),
  });
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={onClose} />,
    { wrapper: TripProvider },
  );

  await screen.findByRole("heading", { name: "경복궁" });
  await user.click(screen.getByRole("button", { name: "상세 창 닫기" }));

  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
});

it("사진도 대표 이미지도 없으면 안내 문구를 보여준다", async () => {
  renderModal(card({ photos: [], thumbnail_url: null }));

  await waitFor(() => {
    expect(screen.getByText("등록된 이미지가 없어요.")).toBeInTheDocument();
  });
  expect(screen.queryByRole("img", { name: /경복궁/ })).not.toBeInTheDocument();
});
