/* 서울시 실시간 요약 블록이 어떤 카드에 뜨고, 값이 빠진 구획을 어떻게 감추는지 검증한다. */

import { render, screen } from "@testing-library/react";
import type { InfoPlaceCard as InfoPlaceCardData } from "../../types";
import { SeoulRealtimeSummarySection } from "./SeoulRealtimeSummarySection";

const baseCard: InfoPlaceCardData = {
  question_type: "concentration",
  answer_fields: {},
  place_id: null,
  place_name: "강남역",
  latitude: null,
  longitude: null,
  thumbnail_url: null,
  overview: null,
  operating_hours: null,
  rest_date: null,
  parking: null,
  parking_fee: null,
  fee: null,
  baby_carriage: null,
  pet: null,
  credit_card: null,
  restroom: null,
  homepage: null,
  population_current_level: "붐빔",
  population_observed_at: "9월 5일 16:25",
  seoul_realtime_summary: {
    population_min: 78000,
    population_max: 80000,
    peak_forecast_hour_label: "오후 5시",
    peak_forecast_level: "약간 붐빔",
    top_age_label: "20대",
    top_age_rate: 29,
    commercial_level: "보통",
    commercial_observed_at: "9월 5일 16:40",
    payment_count: 329,
    payment_amount_min: 7900000,
    payment_amount_max: 8000000,
    top_payment_categories: [
      {
        label: "의료 · 병원",
        activity_level: "한산한",
        payment_amount_min: 1300000,
        payment_amount_max: 1400000,
      },
      {
        label: "음식·음료 · 기타요식",
        activity_level: "바쁜",
        payment_amount_min: 1000000,
        payment_amount_max: 1100000,
      },
    ],
  },
};

describe("SeoulRealtimeSummarySection", () => {
  it("인구·상권 값을 서울시 원문 구간 그대로 보여준다", () => {
    render(<SeoulRealtimeSummarySection card={baseCard} />);

    // 만 명이 넘으면 좁은 타일에서 잘리지 않게 만 단위로 접는다.
    expect(screen.getByText("7.8~8만명")).toBeInTheDocument();
    expect(screen.getByText("오후 5시")).toBeInTheDocument();
    expect(screen.getByText("20대")).toBeInTheDocument();
    expect(screen.getByText("29.0%")).toBeInTheDocument();
    // 단계는 회색 캡션이 아니라 색 칩으로 보여준다.
    expect(screen.getByText("붐빔")).toHaveClass("bg-rust-tint");
    // 원 단위 결제 금액은 만원으로 접는다.
    expect(screen.getByText("790~800만원")).toBeInTheDocument();
    expect(screen.getByText("최근 10분 매출 총액")).toBeInTheDocument();
    expect(screen.getByText("신한카드 내국인 결제 기준 · 서울시 제공")).toBeInTheDocument();
    expect(screen.getByText("329건")).toBeInTheDocument();
  });

  it("결제 금액 상위 업종을 서울시가 준 순서·업종 그대로 싣는다", () => {
    render(<SeoulRealtimeSummarySection card={baseCard} />);

    // 업종 행은 지역 총액의 내역이라 같은 10분 창이다 — 기준을 제목에 밝힌다.
    expect(screen.getByText("최근 10분 매출 Top 2 업종")).toBeInTheDocument();
    // 여행지 카드에 안 어울려도 "의료 · 병원"을 걸러내지 않는다.
    expect(screen.getByText("의료 · 병원")).toBeInTheDocument();
    expect(screen.getByText("130~140만원")).toBeInTheDocument();
  });

  it("상권 미제공 지역(경복궁 등)은 상권 구획을 통째로 감춘다", () => {
    render(
      <SeoulRealtimeSummarySection
        card={{
          ...baseCard,
          seoul_realtime_summary: {
            population_min: 2500,
            population_max: 3000,
            top_age_label: "20대",
            top_age_rate: 21.7,
          },
        }}
      />,
    );

    // 만 명 미만이면 접지 않고 원래 자릿수를 그대로 보여준다.
    expect(screen.getByText("2,500~3,000명")).toBeInTheDocument();
    expect(screen.getByText("실시간 인구")).toBeInTheDocument();
    expect(screen.queryByText("실시간 상권")).not.toBeInTheDocument();
  });

  it("실시간 상권 질문에도 같은 블록을 싣는다", () => {
    render(
      <SeoulRealtimeSummarySection card={{ ...baseCard, question_type: "realtime_commercial" }} />,
    );
    expect(screen.getByText("실시간 상권")).toBeInTheDocument();
  });

  it("서울시 데이터를 조회하지 않는 질문 유형에는 렌더링하지 않는다", () => {
    const { container } = render(
      <SeoulRealtimeSummarySection card={{ ...baseCard, question_type: "operating_hours" }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("요약이 없으면 렌더링하지 않는다", () => {
    const { container } = render(
      <SeoulRealtimeSummarySection card={{ ...baseCard, seoul_realtime_summary: null }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
