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
import type {
  InfoPlaceCard,
  RecommendationItem,
  RecommendationPlaceDetailResponse,
} from "../../types";
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

function recommendationItem(overrides: Partial<RecommendationItem> = {}): RecommendationItem {
  return {
    place_id: "126508",
    name: "경복궁",
    category: "고궁",
    distance_km: 1.2,
    remaining_minutes: 90,
    operating_hours_display: "09:00~18:00",
    environment_type: "outdoor",
    recommendation_reason: "",
    explanations: [],
    warnings: [],
    score: 0,
    feature_scores: {},
    weights_used: {},
    taste_evidence: [],
    ...overrides,
  };
}

beforeEach(() => {
  mockedFetch.mockReset();
});

/*
 * 대표 이미지(thumbnail_url)를 목록 맨 앞에 함께 보여준다. 사진 목록이 있는
 * 6,830곳 중 44%는 대표 이미지가 목록에 없어(2026-09-03 실측), 목록만 그리면
 * 카드에서 보고 눌러 들어온 사진이 상세에서 사라졌다.
 */
it("대표 이미지를 사진 목록 맨 앞에 함께 보여준다", async () => {
  renderModal(
    card({
      photos: [
        { url: "https://tong.visitkorea.or.kr/126508-1.jpg", image_name: "경복궁 (1)" },
        { url: "https://tong.visitkorea.or.kr/126508-2.jpg", image_name: null },
        { url: "https://tong.visitkorea.or.kr/126508-3.jpg", image_name: null },
      ],
    }),
  );

  /* 카드에서 방금 본 사진이 그대로 첫 장이다 — 뒤에 붙이면 상세를 열 때 화면이
     다른 사진으로 갈아치워진 것처럼 보인다. */
  const main = await screen.findByRole("img", { name: "경복궁 사진 1번째" });
  expect(main).toHaveAttribute("src", "https://example.test/gyeongbokgung.jpg");
  expect(screen.getByText("1 / 4")).toBeInTheDocument();

  const list = screen.getByRole("group", { name: "경복궁 사진 목록" });
  expect(within(list).getAllByRole("button")).toHaveLength(4);
});

it("대표 이미지가 목록에도 있으면 두 번 보여주지 않는다", async () => {
  renderModal(
    card({
      thumbnail_url: "https://tong.visitkorea.or.kr/126508-1.jpg",
      photos: [
        { url: "https://tong.visitkorea.or.kr/126508-1.jpg", image_name: null },
        { url: "https://tong.visitkorea.or.kr/126508-2.jpg", image_name: null },
      ],
    }),
  );

  await screen.findByRole("img", { name: "경복궁 사진 1번째" });
  expect(screen.getByText("1 / 2")).toBeInTheDocument();
});

/*
 * 같은 파일을 스킴만 다르게 가리키는 장소가 108곳이다(2026-09-03 실측).
 * places.first_image_url은 http로 적재됐고 place_image_embeddings.origin_url은
 * https다 — 문자열로만 비교하면 그 장소들에서 같은 사진이 두 번 나온다.
 */
it("http와 https만 다른 같은 사진은 한 장으로 본다", async () => {
  renderModal(
    card({
      thumbnail_url: "http://tong.visitkorea.or.kr/cms/resource/15/1868115_image2_1.jpg",
      photos: [
        {
          url: "https://tong.visitkorea.or.kr/cms/resource/15/1868115_image2_1.jpg",
          image_name: null,
        },
      ],
    }),
  );

  /* 한 장으로 합쳐졌으므로 갤러리가 아니라 단일 이미지로 그려진다. */
  const image = await screen.findByRole("img", { name: "경복궁 이미지" });
  /* 먼저 온 대표 이미지의 URL을 그대로 쓴다. */
  expect(image).toHaveAttribute(
    "src",
    "http://tong.visitkorea.or.kr/cms/resource/15/1868115_image2_1.jpg",
  );
  expect(screen.queryByRole("group", { name: "경복궁 사진 목록" })).not.toBeInTheDocument();
});

it("목록에서 고른 사진이 큰 사진으로 바뀐다", async () => {
  const user = userEvent.setup();
  renderModal(
    /* 대표 이미지가 없는 장소다 — 갤러리 이동만 보기 위해 사진 목록만 둔다. */
    card({
      thumbnail_url: null,
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

/*
 * 사진이 늦게 도착해도 화면이 밀리지 않아야 한다. 작은 사진 줄(68px)을 있을 때만
 * 그리면 상세를 열 때마다 그만큼 이동하는데, 사진이 두 장 이상인 장소가 38%뿐이라
 * (8,060곳 중 3,059곳, 2026-09-03 실측) 어느 쪽을 기준으로 잡아도 나머지에서 밀린다.
 * 그래서 세 경우(로딩·갤러리·이미지 없음) 모두 같은 높이를 차지한다.
 */
it("로딩 중에도 작은 사진 줄 자리를 미리 잡아 둔다", async () => {
  /* 응답을 붙잡아 두고 로딩 상태를 본다. */
  let resolveDetail!: (value: RecommendationPlaceDetailResponse) => void;
  mockedFetch.mockReturnValue(
    new Promise((resolve) => {
      resolveDetail = resolve;
    }),
  );
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );

  expect(screen.getByTestId("photo-strip-slot")).toBeInTheDocument();

  resolveDetail({
    status: "success",
    requested_place_id: "126508",
    place_card: card({
      photos: [
        { url: "https://tong.visitkorea.or.kr/126508-1.jpg", image_name: null },
        { url: "https://tong.visitkorea.or.kr/126508-2.jpg", image_name: null },
      ],
    }),
  });

  await screen.findByRole("group", { name: "경복궁 사진 목록" });
  /* 응답 뒤에도 같은 자리에 같은 높이의 줄이 있다 — 껍데기가 바뀌지 않는다. */
  expect(screen.getAllByTestId("photo-strip-slot")).toHaveLength(1);
});

/*
 * 운영시간은 추천 카드를 만들 때 D가 이미 계산해 item.operating_hours_display에
 * 실어 보낸 값이다 — 카드 목록에서 이미 본 값을, 상세 조회(fetchRecommendationPlaceDetails)
 * 응답을 기다리지 않고 먼저 보여준다.
 */
it("로딩 중에도 이미 아는 운영시간을 먼저 보여준다", async () => {
  let resolveDetail!: (value: RecommendationPlaceDetailResponse) => void;
  mockedFetch.mockReturnValue(
    new Promise((resolve) => {
      resolveDetail = resolve;
    }),
  );
  render(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ operating_hours_display: "09:00~18:00", remaining_minutes: 90 })}
      onClose={() => {}}
    />,
    { wrapper: TripProvider },
  );

  /* 상세 조회 응답이 오기 전인데도 카드가 이미 아는 값이 바로 보인다. */
  expect(await screen.findByText("운영시간")).toBeInTheDocument();
  expect(screen.getByText("09:00~18:00 · 영업 중")).toBeInTheDocument();

  resolveDetail({
    status: "success",
    requested_place_id: "126508",
    place_card: card({ operating_hours: "매일 10:00~19:00" }),
  });

  /* 상세 조회 값이 도착하면 그쪽으로 바뀐다 — 미리보기 값이 남아 있지 않는다. */
  await screen.findByText("매일 10:00~19:00 · 영업 중");
  expect(screen.queryByText("09:00~18:00 · 영업 중")).not.toBeInTheDocument();
});

/* INFO·사진 검색 경로는 item 자체가 없어 참고할 값이 없다 — 근거 없이 지어내지 않는다. */
it("운영시간을 미리 알 수 없으면 미리보기를 그리지 않는다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );

  expect(screen.queryByText("운영시간")).not.toBeInTheDocument();
});

/*
 * item.image_url도 operating_hours_display와 같은 이유로 이미 아는 값이다 —
 * 상세 조회를 기다리지 않고 카드에서 본 그 사진을 먼저 보여준다.
 */
/*
 * 큰 사진과 운영시간을 카드에서 이미 아는 값으로 먼저 채우고 나면, 상세 조회가
 * 여전히 진행 중이라는 사실을 알려줄 곳이 작은 사진 줄밖에 남지 않는다. 그래서
 * 첫 칸에 회전하는 아이콘을 얹는다.
 */
it("상세 조회가 끝나기 전엔 작은 사진 줄 첫 칸에 로딩 아이콘이 돈다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ image_url: "https://example.test/card-thumbnail.jpg" })}
      onClose={() => {}}
    />,
    { wrapper: TripProvider },
  );

  expect(await screen.findByTestId("photo-strip-loading-spinner")).toBeInTheDocument();
});

it("로딩 중에도 이미 아는 대표 사진을 먼저 보여준다", async () => {
  let resolveDetail!: (value: RecommendationPlaceDetailResponse) => void;
  mockedFetch.mockReturnValue(
    new Promise((resolve) => {
      resolveDetail = resolve;
    }),
  );
  render(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ image_url: "https://example.test/card-thumbnail.jpg" })}
      onClose={() => {}}
    />,
    { wrapper: TripProvider },
  );

  /* 상세 조회 응답이 오기 전인데도 카드가 이미 아는 사진이 바로 보인다. */
  const preview = await screen.findByRole("img", { name: "경복궁 이미지" });
  expect(preview).toHaveAttribute("src", "https://example.test/card-thumbnail.jpg");
  expect(screen.queryByText("상세 정보를 불러오는 중...")).not.toBeInTheDocument();

  resolveDetail({
    status: "success",
    requested_place_id: "126508",
    place_card: card({ thumbnail_url: "https://example.test/detail-thumbnail.jpg", photos: [] }),
  });

  /* 상세 조회 값이 도착하면 그쪽 사진으로 바뀐다 — 카드 사진이 남아 있지 않는다. */
  await waitFor(() =>
    expect(screen.getByRole("img", { name: "경복궁 이미지" })).toHaveAttribute(
      "src",
      "https://example.test/detail-thumbnail.jpg",
    ),
  );
});

/*
 * 카드 썸네일(작은 사진)과 상세 사진(원본 크기)은 같은 장소라도 화질·크롭이
 * 다르다 — 카드는 recommendation_cards.py가, 상세는 hybrid_place_details.py가
 * 서로 반대 우선순위로 고르기 때문이다. 그대로 바꿔치우면 사라졌다 나타나는
 * 것처럼 번쩍인다. 카드 썸네일을 흐리게 계속 깔아 둬서 "흐리다가 선명해진다"로
 * 읽히게 한다.
 */
it("상세 사진으로 바뀔 때 카드 썸네일을 흐리게 깔아 자연스럽게 잇는다", async () => {
  let resolveDetail!: (value: RecommendationPlaceDetailResponse) => void;
  mockedFetch.mockReturnValue(
    new Promise((resolve) => {
      resolveDetail = resolve;
    }),
  );
  render(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ image_url: "https://example.test/card-thumbnail.jpg" })}
      onClose={() => {}}
    />,
    { wrapper: TripProvider },
  );
  await screen.findByRole("img", { name: "경복궁 이미지" });
  /* 로딩 중에는 이어 붙일 상세 사진이 아직 없어 흐린 배경이 필요 없다. */
  expect(screen.queryByTestId("photo-blur-placeholder")).not.toBeInTheDocument();

  resolveDetail({
    status: "success",
    requested_place_id: "126508",
    place_card: card({ thumbnail_url: "https://example.test/detail-thumbnail.jpg", photos: [] }),
  });
  await waitFor(() =>
    expect(screen.getByRole("img", { name: "경복궁 이미지" })).toHaveAttribute(
      "src",
      "https://example.test/detail-thumbnail.jpg",
    ),
  );

  /* 상세 사진이 자리를 넘겨받은 뒤에도 카드 썸네일이 흐린 배경으로 함께 있다 —
     빈 회색 칸으로 뚝 끊기지 않는다. */
  expect(screen.getByTestId("photo-blur-placeholder")).toHaveAttribute(
    "src",
    "https://example.test/card-thumbnail.jpg",
  );
});

it("대표 사진을 미리 알 수 없으면 로딩 문구를 그대로 보여준다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );

  expect(await screen.findByText("상세 정보를 불러오는 중...")).toBeInTheDocument();
});

it("사진이 한 장뿐이어도 작은 사진 줄 자리는 그대로 남는다", async () => {
  renderModal(card({ photos: [] }));

  await screen.findByRole("img", { name: "경복궁 이미지" });

  /* 고를 사진이 없어 버튼은 없지만, 자리는 남아 있어야 화면이 밀리지 않는다. */
  expect(screen.getAllByTestId("photo-strip-slot")).toHaveLength(1);
  expect(screen.queryByRole("group", { name: "경복궁 사진 목록" })).not.toBeInTheDocument();
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

it("무장애 값이 있으면 편의시설 구획으로 그린다", async () => {
  renderModal(
    card({
      accessible_restroom: "장애인 화장실 있음(1층)",
      elevator: "엘리베이터 있음",
      guide_dog: "보조견 동반 가능함",
    }),
  );

  const heading = await screen.findByText("편의시설");
  const section = heading.parentElement as HTMLElement;
  expect(within(section).getByText("장애인 화장실")).toBeInTheDocument();
  expect(within(section).getByText("장애인 화장실 있음(1층)")).toBeInTheDocument();
  expect(within(section).getByText("승강기")).toBeInTheDocument();
  expect(within(section).getByText("보조견 동반")).toBeInTheDocument();
  // 값이 없는 항목은 줄 자체가 없다. 빈 값을 "없음"으로 그리면 있는 시설을
  // 없다고 말하게 된다.
  expect(within(section).queryByText("휠체어 대여")).not.toBeInTheDocument();
  expect(within(section).queryByText("수유·기저귀")).not.toBeInTheDocument();
});

it("무장애 값이 하나도 없으면 편의시설 구획을 숨긴다", async () => {
  renderModal(card({ parking: "가능 (240대)" }));

  // 상세가 그려진 뒤에 확인한다 — 조회 전이면 아직 아무 구획도 없다.
  expect(await screen.findByText("주차")).toBeInTheDocument();
  expect(screen.queryByText("편의시설")).not.toBeInTheDocument();
});

it("유모차는 무장애 값과 기존 값이 함께 보이지 않는다", async () => {
  // C가 둘 중 하나만 채워 보낸다(둘 다 있는 34곳 중 21곳에서 서로 반대라서).
  renderModal(card({ baby_carriage: null, stroller_rental: "대여가능(10대)" }));

  const heading = await screen.findByText("편의시설");
  const section = heading.parentElement as HTMLElement;
  expect(within(section).getByText("유모차 대여")).toBeInTheDocument();
  expect(within(section).getByText("대여가능(10대)")).toBeInTheDocument();
  // 위 표의 "유모차" 줄은 값이 비어 나오지 않는다.
  expect(screen.queryByText("유모차")).not.toBeInTheDocument();
});
