/*
 * 장소별 취향 태그 표. 추천 결과 메시지에서 갈라져 나오면서 이 파일로 옮겨왔다
 * (원래는 RecommendationResultMessage.test.tsx에 있었다).
 */

import { render, screen, within } from "@testing-library/react";

import { PreferenceTagSummaryTable } from "./PreferenceTagSummaryTable";

it("장소별 취향 태그와 문서 단위 언급 수를 표로 표시한다", () => {
  render(
    <PreferenceTagSummaryTable
      items={[
        {
          place_id: "place-1",
          name: "아키비스트 서촌",
          preference_tags: [
            { code: "quiet", label: "조용히 머물기 좋은", mention_count: 7 },
            { code: "date", label: "데이트하기 좋은", mention_count: 4 },
            { code: "walk", label: "산책하기 좋은", mention_count: 3 },
            { code: "nature", label: "자연을 즐기기 좋은", mention_count: 2 },
          ],
        },
      ]}
      language="ko"
    />,
  );

  const table = screen.getByRole("table", { name: "장소별 방문자 취향 태그" });
  expect(
    screen.getByText("네이버 블로그 후기와 구글 지도 리뷰 약 30건에서 언급된 태그입니다."),
  ).toBeInTheDocument();
  expect(within(table).getByText("아키비스트 서촌")).toBeInTheDocument();
  expect(within(table).getByText("조용히 머물기 좋은")).toBeInTheDocument();
  expect(within(table).getByText("(7)")).toBeInTheDocument();
  expect(within(table).getByText("데이트하기 좋은")).toBeInTheDocument();
  expect(within(table).getByText("(4)")).toBeInTheDocument();
  // 카드가 좁아 두 개까지만 싣는다 — 나머지는 상세에서 본다.
  expect(within(table).queryByText("산책하기 좋은")).not.toBeInTheDocument();
  expect(within(table).queryByText("자연을 즐기기 좋은")).not.toBeInTheDocument();
});

it("태그가 하나도 없으면 표 자체를 그리지 않는다", () => {
  const { container } = render(
    <PreferenceTagSummaryTable
      items={[{ place_id: "place-1", name: "아키비스트 서촌" }]}
      language="ko"
    />,
  );

  expect(container).toBeEmptyDOMElement();
});
