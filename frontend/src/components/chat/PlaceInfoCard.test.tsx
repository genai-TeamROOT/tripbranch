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

  await user.click(screen.getByRole("button", { name: /경복궁.*상세 정보 보기/i }));

  expect(screen.getByText("조선 왕조의 법궁이다.")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "경복궁 썸네일" })).toBeInTheDocument();
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
