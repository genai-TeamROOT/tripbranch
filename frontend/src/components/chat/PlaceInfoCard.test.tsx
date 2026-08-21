/* INFO 장소 카드의 접기/펼치기와 결측값 숨김을 검증한다. */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { fetchRecommendationPlaceDetails } from "../../api/trip";
import { TripProvider } from "../../state/TripContext";
import type { InfoPlaceCard as InfoPlaceCardData } from "../../types";
import { PlaceInfoCard } from "./PlaceInfoCard";

// 상세 모달이 useTripState(현재 위치)를 읽으므로 TripProvider로 감싼다.
const renderWithTrip = (ui: Parameters<typeof render>[0]) =>
  render(ui, { wrapper: TripProvider });

vi.mock("../../api/trip", () => ({
  fetchRecommendationPlaceDetails: vi.fn(),
}));

const card: InfoPlaceCardData = {
  question_type: "parking",
  answer_fields: { parking: "가능", parking_fee: "무료" },
  place_id: "126508",
  place_name: "경복궁",
  latitude: null,
  longitude: null,
  thumbnail_url: "https://example.test/gyeongbokgung.jpg",
  overview: "조선 왕조의 법궁이다.",
  operating_hours: "09:00~18:00",
  rest_date: "매주 화요일 ※ 단, 정기휴일이 공휴일 및 대체공휴일과 겹치면 개방합니다.",
  parking: "가능",
  parking_fee: "무료",
  fee: "성인 3,000원",
  baby_carriage: "가능",
  pet: null,
  credit_card: "가능",
  restroom: "있음",
  homepage: "https://example.test",
};

it("질문 답과 썸네일은 바로 보이고, 클릭하면 같은 상세 모달을 연다", async () => {
  const user = userEvent.setup();
  renderWithTrip(<PlaceInfoCard card={card} />);

  expect(screen.getByText("주차 요금")).toBeInTheDocument();
  expect(screen.queryByText("조선 왕조의 법궁이다.")).not.toBeInTheDocument();
  expect(screen.getByRole("img", { name: "경복궁 이미지" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "경복궁 상세 보기" }));

  const dialog = screen.getByRole("dialog", { name: "경복궁" });
  expect(within(dialog).getByText("조선 왕조의 법궁이다.")).toBeInTheDocument();
  expect(within(dialog).getByRole("img", { name: "경복궁 이미지" })).toBeInTheDocument();
  expect(within(dialog).getByText("성인 3,000원")).toBeInTheDocument();
  expect(
    within(dialog).getByText("※ 단, 정기휴일이 공휴일 및 대체공휴일과 겹치면 개방합니다."),
  ).toHaveClass("text-xs", "text-gray-500");
  // 홈페이지는 하단 별도 링크가 아니라 "관련 정보" 박스 안에 클릭 가능한 링크로 뜬다.
  // question_type이 "parking"이라 answer_fields엔 없지만(카드 최상위 필드), 박스가
  // 합성해서 보여준다.
  expect(within(dialog).getByRole("link", { name: "https://example.test" })).toHaveAttribute(
    "href",
    "https://example.test",
  );
});

it("관련 정보의 URL은 클릭 가능한 링크로 보여준다", async () => {
  const user = userEvent.setup();
  renderWithTrip(
    <PlaceInfoCard
      card={{ ...card, answer_fields: { homepage: "https://instagram.com/gyeongbokgung" } }}
    />,
  );

  await user.click(screen.getByRole("button", { name: "경복궁 상세 보기" }));

  const dialog = within(screen.getByRole("dialog"));
  expect(
    dialog.getByRole("link", { name: "https://instagram.com/gyeongbokgung" }),
  ).toHaveAttribute("href", "https://instagram.com/gyeongbokgung");
});

it("프로토콜 없는 www. 도메인도 https://를 붙여 링크로 보여준다", async () => {
  // 실측(TourAPI homepage 필드): 3.6%가 "www.xxx.xxx" 형태로 온다 — http(s):// 없이.
  const user = userEvent.setup();
  renderWithTrip(
    <PlaceInfoCard card={{ ...card, answer_fields: { homepage: "www.royalpalace.go.kr" } }} />,
  );

  await user.click(screen.getByRole("button", { name: "경복궁 상세 보기" }));

  const dialog = within(screen.getByRole("dialog"));
  const link = dialog.getByRole("link", { name: "www.royalpalace.go.kr" });
  expect(link).toHaveAttribute("href", "https://www.royalpalace.go.kr");
});

it("없는 값은 카드에 임의 문구나 빈 이미지로 표시하지 않는다", () => {
  renderWithTrip(<PlaceInfoCard card={{ ...card, thumbnail_url: null, overview: null, pet: null }} />);

  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.queryByText("정보 없음")).not.toBeInTheDocument();
});

it("요금 항목과 ※ 안내를 각각 줄바꿈해 표시한다", async () => {
  const user = userEvent.setup();
  const fee = "- 성인 10,000원 - 학생 7,000원 ※ 무료: 장애인";
  renderWithTrip(<PlaceInfoCard card={{ ...card, answer_fields: { fee }, fee }} />);

  expect(screen.getByText("- 성인 10,000원 - 학생 7,000원 ※ 무료: 장애인")).toHaveClass(
    "whitespace-pre-line",
  );

  await user.click(screen.getByRole("button", { name: "경복궁 상세 보기" }));

  const dialog = within(screen.getByRole("dialog"));
  expect(dialog.getByText("- 성인 10,000원")).toHaveClass("whitespace-pre-line");
  expect(dialog.getByText("- 학생 7,000원")).toHaveClass("whitespace-pre-line");
  expect(dialog.getByText("※ 무료: 장애인")).toHaveClass("text-xs", "text-gray-500");
});

it("붙어 있는 월별 운영시간을 기간별 카드로 나눈다", async () => {
  const user = userEvent.setup();
  const operatingHours =
    "[1월~2월/11월~12월]09:00~17:00 (입장마감 16:00)[3월~5월/9월~10월]09:00~18:00 (입장마감 17:00)[6월~8월]09:00~18:30 (입장마감 17:30)";
  renderWithTrip(<PlaceInfoCard card={{ ...card, answer_fields: { operating_hours: operatingHours }, operating_hours: operatingHours }} />);

  expect(screen.getByText("1월~2월 · 11월~12월")).toBeInTheDocument();
  expect(screen.getByText("09:00–17:00 · 입장 마감 16:00")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "경복궁 상세 보기" }));

  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("1월~2월 · 11월~12월")).toBeInTheDocument();
  expect(within(dialog).getByText("09:00–17:00 · 입장 마감 16:00")).toBeInTheDocument();
  expect(within(dialog).getByText("6월~8월")).toBeInTheDocument();
  expect(within(dialog).getByText("09:00–18:30 · 입장 마감 17:30")).toBeInTheDocument();
});

it("주소 INFO 카드도 클릭하면 전체 장소 상세를 보강 조회한다", async () => {
  const user = userEvent.setup();
  const minimalCard: InfoPlaceCardData = {
    ...card,
    question_type: "location_info",
    answer_fields: { address: "서울특별시 종로구 사직로 161" },
    thumbnail_url: null,
    overview: null,
    operating_hours: null,
    rest_date: null,
    parking: null,
    parking_fee: null,
    fee: null,
    baby_carriage: null,
    credit_card: null,
    restroom: null,
    homepage: null,
  };
  vi.mocked(fetchRecommendationPlaceDetails).mockResolvedValue({
    status: "success",
    requested_place_id: "126508",
    place_card: card,
  });

  renderWithTrip(<PlaceInfoCard card={minimalCard} />);
  await user.click(screen.getByRole("button", { name: "경복궁 상세 보기" }));

  await waitFor(() => {
    expect(fetchRecommendationPlaceDetails).toHaveBeenCalledWith({
      place_id: "126508",
      place_name: "경복궁",
    });
  });
  const dialog = screen.getByRole("dialog", { name: "경복궁" });
  expect(within(dialog).getByText("조선 왕조의 법궁이다.")).toBeInTheDocument();
  expect(within(dialog).getByText("서울특별시 종로구 사직로 161")).toBeInTheDocument();
});

it("혼잡도 카드(place_id 없음)도 이름으로 상세를 보강 조회한다", async () => {
  const user = userEvent.setup();
  const concentrationCard: InfoPlaceCardData = {
    ...card,
    question_type: "concentration",
    place_id: null,
    place_name: "창덕궁",
    answer_fields: { concentration: "이번 주말 · 다소 혼잡" },
    thumbnail_url: null,
    overview: null,
  };
  vi.mocked(fetchRecommendationPlaceDetails).mockResolvedValue({
    status: "success",
    requested_place_id: null,
    place_card: { ...card, place_name: "창덕궁", overview: "창덕궁 상세 개요" },
  });

  renderWithTrip(<PlaceInfoCard card={concentrationCard} />);
  await user.click(screen.getByRole("button", { name: "창덕궁 상세 보기" }));

  await waitFor(() => {
    expect(fetchRecommendationPlaceDetails).toHaveBeenCalledWith(
      expect.objectContaining({ place_name: "창덕궁" }),
    );
  });
  const dialog = screen.getByRole("dialog", { name: "창덕궁" });
  expect(within(dialog).getByText("창덕궁 상세 개요")).toBeInTheDocument();
});
