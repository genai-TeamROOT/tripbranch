/* 혼잡도 게이지·예측 막대그래프의 색상 매핑과 결측값 처리를 검증한다. */

import { render, screen } from "@testing-library/react";
import type { InfoPlaceCard as InfoPlaceCardData } from "../../types";
import {
  CongestionLevelGauge,
  ConcentrationForecastBars,
  PopulationForecastBars,
  RoadTrafficStatusSection,
} from "./CongestionForecastBars";

const baseCard: InfoPlaceCardData = {
  question_type: "concentration",
  answer_fields: {},
  place_id: null,
  place_name: "경복궁",
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
};

describe("CongestionLevelGauge", () => {
  it("현재 단계에 마커와 굵은 라벨을 표시한다", () => {
    render(<CongestionLevelGauge level="약간 붐빔" />);

    expect(screen.getByLabelText("현재 인구 혼잡도 약간 붐빔")).toBeInTheDocument();
    expect(screen.getByText("약간 붐빔")).toHaveClass("font-semibold");
    expect(screen.getByText("여유")).not.toHaveClass("font-semibold");
  });

  it("레벨이 없으면 아무것도 렌더링하지 않는다", () => {
    const { container } = render(<CongestionLevelGauge level={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("알 수 없는 레벨 문자열이 와도 깨지지 않는다", () => {
    render(<CongestionLevelGauge level="예측불가" />);
    expect(screen.getByLabelText("현재 인구 혼잡도 예측불가")).toBeInTheDocument();
    // 4단계 중 어디에도 해당하지 않으므로 강조 라벨이 없다.
    for (const label of ["여유", "보통", "약간 붐빔", "붐빔"]) {
      expect(screen.getByText(label)).not.toHaveClass("font-semibold");
    }
  });
});

describe("PopulationForecastBars", () => {
  it("예측이 없으면 렌더링하지 않는다", () => {
    const { container } = render(<PopulationForecastBars card={baseCard} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("혼잡도 단계별로 다른 색상 막대를 그린다", () => {
    const card: InfoPlaceCardData = {
      ...baseCard,
      population_forecasts: [
        { forecast_at: "2026-08-20 15:00", congestion_level: "여유", population_min: null, population_max: null },
        { forecast_at: "2026-08-20 16:00", congestion_level: "붐빔", population_min: null, population_max: null },
        { forecast_at: "2026-08-20 17:00", congestion_level: "모름", population_min: null, population_max: null },
      ],
    };
    const { container } = render(<PopulationForecastBars card={card} />);

    const bars = container.querySelectorAll(
      '[aria-label="현재부터 향후 12시간 인구 혼잡도 예측"] > div > div > div',
    );
    expect(bars[0]).toHaveClass("bg-emerald-500");
    expect(bars[1]).toHaveClass("bg-red-500");
    // 알 수 없는 레벨은 회색 fallback으로 처리해 깨지지 않는다.
    expect(bars[2]).toHaveClass("bg-gray-400");
  });

  it("현재 시각 막대를 점선 구분선과 강조 테두리로 앞쪽에 따로 보여준다", () => {
    const card: InfoPlaceCardData = {
      ...baseCard,
      population_current_level: "붐빔",
      population_forecasts: [
        { forecast_at: "2026-08-20 16:00", congestion_level: "여유", population_min: null, population_max: null },
      ],
    };
    const { container } = render(<PopulationForecastBars card={card} />);

    const bars = container.querySelectorAll(
      '[aria-label="현재부터 향후 12시간 인구 혼잡도 예측"] > div > div > div',
    );
    // 첫 번째 막대는 예측이 아니라 "현재" — 현재 레벨(붐빔) 색이어야 한다.
    expect(bars[0]).toHaveClass("bg-red-500");
    expect(bars[1]).toHaveClass("bg-emerald-500");
    expect(screen.getByText("현재")).toHaveClass("font-semibold");

    const currentTrack = bars[0].parentElement;
    expect(currentTrack).toHaveClass("ring-2");
    expect(currentTrack?.parentElement).toHaveClass("border-dashed");
  });

  it("현재 혼잡도 레벨이 없으면 '현재' 막대를 추가하지 않는다", () => {
    const card: InfoPlaceCardData = {
      ...baseCard,
      population_forecasts: [
        { forecast_at: "2026-08-20 16:00", congestion_level: "여유", population_min: null, population_max: null },
      ],
    };
    render(<PopulationForecastBars card={card} />);
    expect(screen.queryByText("현재")).not.toBeInTheDocument();
  });

  it("피크 전망 요약이 있으면 강조 문구로 보여준다", () => {
    const card: InfoPlaceCardData = {
      ...baseCard,
      population_forecasts: [
        { forecast_at: "2026-08-20 15:00", congestion_level: "붐빔", population_min: null, population_max: null },
      ],
      population_peak_forecast_summary: "15시(1시간 후)에 가장 붐빌 것으로 예상돼요. 혼잡정도는 붐빔일 것으로 예상돼요.",
    };
    render(<PopulationForecastBars card={card} />);

    expect(
      screen.getByText("15시(1시간 후)에 가장 붐빌 것으로 예상돼요. 혼잡정도는 붐빔일 것으로 예상돼요."),
    ).toBeInTheDocument();
  });
});

describe("ConcentrationForecastBars", () => {
  it("집중률 단계별로 다른 색상 막대를 그린다", () => {
    const card: InfoPlaceCardData = {
      ...baseCard,
      concentration_forecasts: [
        { forecast_date: "2026-08-20", concentration_rate: 20, concentration_level: "quiet", concentration_label: "한적함" },
        { forecast_date: "2026-08-21", concentration_rate: 90, concentration_level: "crowded", concentration_label: "혼잡" },
      ],
    };
    const { container } = render(<ConcentrationForecastBars card={card} />);

    const bars = container.querySelectorAll('[aria-label="관광지 혼잡도 7일 예측"] > div > div > div');
    expect(bars[0]).toHaveClass("bg-emerald-500");
    expect(bars[1]).toHaveClass("bg-red-500");
  });
});

describe("CongestionLevelGauge와 levels prop", () => {
  it("3단계(도로소통) 배열을 넘기면 그 순서로 게이지를 그린다", () => {
    render(
      <CongestionLevelGauge
        level="정체"
        levels={[
          { label: "원활", color: "bg-emerald-500" },
          { label: "서행", color: "bg-amber-400" },
          { label: "정체", color: "bg-red-500" },
        ]}
        ariaLabelPrefix="현재 도로소통 단계"
      />,
    );

    expect(screen.getByLabelText("현재 도로소통 단계 정체")).toBeInTheDocument();
    expect(screen.getByText("정체")).toHaveClass("font-semibold");
    // 인구 혼잡도 라벨("여유" 등)이 섞여 나오면 안 된다.
    expect(screen.queryByText("여유")).not.toBeInTheDocument();
  });
});

describe("RoadTrafficStatusSection", () => {
  const trafficCard: InfoPlaceCardData = {
    ...baseCard,
    question_type: "realtime_traffic",
    answer_fields: {
      "도로소통 단계": "원활",
      "평균 주행속도": "32km/h",
      "안내": "해당 장소로 이동·진입하는 도로가 크게 막히지 않아요.",
    },
  };

  it("단계 게이지·평균속도·안내문구를 보여준다", () => {
    render(<RoadTrafficStatusSection card={trafficCard} />);

    expect(screen.getByLabelText("현재 도로소통 단계 원활")).toBeInTheDocument();
    expect(screen.getByText("평균 32km/h")).toBeInTheDocument();
    expect(
      screen.getByText("해당 장소로 이동·진입하는 도로가 크게 막히지 않아요."),
    ).toBeInTheDocument();
  });

  it("question_type이 realtime_traffic이 아니면 렌더링하지 않는다", () => {
    const { container } = render(
      <RoadTrafficStatusSection card={{ ...trafficCard, question_type: "concentration" }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("단계 값이 없으면 렌더링하지 않는다", () => {
    const { container } = render(
      <RoadTrafficStatusSection card={{ ...trafficCard, answer_fields: {} }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
