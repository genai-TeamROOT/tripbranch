/* INFO 장소 카드의 접기/펼치기와 결측값 숨김을 검증한다. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { InfoPlaceCard as InfoPlaceCardData } from "../../types";
import { PlaceInfoCard } from "./PlaceInfoCard";

const card: InfoPlaceCardData = {
  question_type: "parking",
  answer_fields: { parking: "가능", parking_fee: "무료" },
  place_id: "126508",
  place_name: "경복궁",
  thumbnail_url: "https://example.test/gyeongbokgung.jpg",
  overview: "조선 왕조의 법궁이다.",
  operating_hours: "09:00~18:00",
  rest_date: null,
  parking: "가능",
  parking_fee: "무료",
  fee: "성인 3,000원",
  baby_carriage: "가능",
  pet: null,
  credit_card: "가능",
  restroom: "있음",
  homepage: "https://example.test",
};

it("질문 답은 바로 보이고, 클릭하면 전체 상세를 펼친다", async () => {
  const user = userEvent.setup();
  render(<PlaceInfoCard card={card} />);

  expect(screen.getByText("주차 요금")).toBeInTheDocument();
  expect(screen.queryByText("조선 왕조의 법궁이다.")).not.toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /경복궁.*상세/i }));

  expect(screen.getByText("조선 왕조의 법궁이다.")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "경복궁 이미지" })).toBeInTheDocument();
  expect(screen.getByText("성인 3,000원")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "공식 홈페이지 보기" })).toHaveAttribute(
    "href",
    "https://example.test",
  );
});

it("없는 값은 카드에 임의 문구나 빈 이미지로 표시하지 않는다", () => {
  render(<PlaceInfoCard card={{ ...card, thumbnail_url: null, overview: null, pet: null }} />);

  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.queryByText("정보 없음")).not.toBeInTheDocument();
});

it("요금 항목과 ※ 안내를 각각 줄바꿈해 표시한다", async () => {
  const user = userEvent.setup();
  const fee = "- 성인 10,000원 - 학생 7,000원 ※ 무료: 장애인";
  render(<PlaceInfoCard card={{ ...card, answer_fields: { fee }, fee }} />);

  expect(screen.getByText("- 성인 10,000원 - 학생 7,000원 ※ 무료: 장애인")).toHaveClass(
    "whitespace-pre-line",
  );

  await user.click(screen.getByRole("button", { name: /경복궁.*상세/i }));

  expect(screen.getByText("- 성인 10,000원 - 학생 7,000원 ※ 무료: 장애인")).toHaveClass(
    "whitespace-pre-line",
  );
});

it("붙어 있는 월별 운영시간을 기간별 카드로 나눈다", async () => {
  const user = userEvent.setup();
  const operatingHours =
    "[1월~2월/11월~12월]09:00~17:00 (입장마감 16:00)[3월~5월/9월~10월]09:00~18:00 (입장마감 17:00)[6월~8월]09:00~18:30 (입장마감 17:30)";
  render(<PlaceInfoCard card={{ ...card, answer_fields: { operating_hours: operatingHours }, operating_hours: operatingHours }} />);

  expect(screen.getByText("1월~2월 · 11월~12월")).toBeInTheDocument();
  expect(screen.getByText("09:00–17:00 · 입장 마감 16:00")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /경복궁.*상세/i }));

  expect(screen.getByText("1월~2월 · 11월~12월")).toBeInTheDocument();
  expect(screen.getByText("09:00–17:00 · 입장 마감 16:00")).toBeInTheDocument();
  expect(screen.getByText("6월~8월")).toBeInTheDocument();
  expect(screen.getByText("09:00–18:30 · 입장 마감 17:30")).toBeInTheDocument();
});
