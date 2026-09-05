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
import { openNaverDirections } from "../../utils/naverDirections";
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
const mockedDirections = vi.mocked(openNaverDirections);

/* 길찾기 버튼은 현재 위치가 있어야 나온다. TripProvider가 sessionStorage에서
   복원하므로 저장 형식을 직접 심는다(SchedulePage.test.tsx와 같은 방식). */
function seedDeviceLocation() {
  sessionStorage.setItem(
    "tripbranch_state",
    JSON.stringify({
      version: 6,
      state: {
        language: "ko",
        user_input: "",
        interpreted_conditions: null,
        recommendations: [],
        unverified_recommendations: [],
        shown_place_ids: [],
        messages: [],
        auditTurns: [],
        phase: "ready",
        error: null,
        session_id: null,
        device_location: "37.5665,126.9780",
        device_location_captured_at: Date.now(),
        device_location_snoozed_until: null,
        awaiting_clarification: false,
        saved_places: [],
        agentProgress: null,
        streamingIntent: null,
      },
    }),
  );
}

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
  mockedDirections.mockReset();
  sessionStorage.clear();
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

/*
 * 카드 이미지가 없는 장소 844곳 중 843곳(99.9%)은 상세 사진도 0장이다(2026-09-05
 * 실측). 열 때 이미 아는 사실이므로 응답을 기다렸다가 자리를 접지 않는다 —
 * 기다렸다 접으면 그 844곳이 전부 밀린다.
 */
it("카드에 이미지가 없으면 사진 영역을 처음부터 그리지 않는다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ image_url: null })}
      onClose={() => {}}
    />,
    { wrapper: TripProvider },
  );

  await screen.findByRole("heading", { name: "경복궁" });

  expect(screen.queryByTestId("photo-strip-slot")).not.toBeInTheDocument();
  expect(screen.queryByText("상세 정보를 불러오는 중...")).not.toBeInTheDocument();
});

it("카드에 이미지가 없으면 응답이 와도 사진 영역이 생기지 않는다", async () => {
  let resolveDetail!: (value: RecommendationPlaceDetailResponse) => void;
  mockedFetch.mockReturnValue(
    new Promise((resolve) => {
      resolveDetail = resolve;
    }),
  );
  render(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ image_url: null })}
      onClose={() => {}}
    />,
    { wrapper: TripProvider },
  );

  resolveDetail({
    status: "success",
    requested_place_id: "126508",
    place_card: card({ photos: [], thumbnail_url: null }),
  });

  await screen.findByRole("heading", { name: "경복궁" });

  // 로딩 전후로 같은 모양이라 화면이 밀리지 않는다.
  expect(screen.queryByTestId("photo-strip-slot")).not.toBeInTheDocument();
  expect(screen.queryByText("등록된 이미지가 없어요.")).not.toBeInTheDocument();
});

/*
 * 시트 높이는 내용과 무관하게 고정이다.
 *
 * 내용 높이로 정하면 상세 응답이 도착할 때 화면이 위로 자란다 — 개요·관련 정보는
 * 응답 전에 자리를 잡을 수 없기 때문이다. 사진 영역이 있던 시절에는 그 283px이
 * 로딩 시점에 상한을 채워 성장이 스크롤로 흡수됐을 뿐이다.
 */
it("상세 응답 전후로 시트 높이가 바뀌지 않는다", async () => {
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

  const sheet = screen.getByTestId("place-detail-sheet");
  const before = sheet.className;

  resolveDetail({
    status: "success",
    requested_place_id: "126508",
    place_card: card({
      overview: "긴 개요 문장이 응답과 함께 도착한다. ".repeat(20),
      photos: [{ url: "https://tong.visitkorea.or.kr/126508-1.jpg", image_name: null }],
    }),
  });

  await screen.findByRole("heading", { name: "경복궁" });

  expect(sheet.className).toBe(before);
  expect(sheet.className).toContain("h-[88vh]");
  // max-h로 두면 내용이 상한 밑일 때 시트가 내용만큼만 커져서 성장이 보인다.
  expect(sheet.className).not.toContain("max-h-[88vh]");
});

it("사진 영역이 없는 장소도 같은 높이로 열린다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ image_url: null })}
      onClose={() => {}}
    />,
    { wrapper: TripProvider },
  );

  const sheet = screen.getByTestId("place-detail-sheet");
  // "h-[88vh]"는 "max-h-[88vh]"의 부분 문자열이라 둘 다 본다.
  expect(sheet.className).toContain("h-[88vh]");
  expect(sheet.className).not.toContain("max-h-[88vh]");
  // 사진 영역을 접은 것이 시트 크기까지 줄이지는 않는다 — 정보가 위로 올라올 뿐이다.
  expect(screen.queryByTestId("photo-strip-slot")).not.toBeInTheDocument();
});

it("카드에 이미지가 없어도 상세에 사진이 있으면 갤러리를 보여준다", async () => {
  /*
   * 카드 이미지가 없는 844곳 중 1곳은 상세 사진이 있다. 미리 접어 둔 자리가
   * 그때는 펴져야 한다 — 밀리더라도 사진을 감추는 것보다 낫다.
   */
  mockedFetch.mockResolvedValue({
    status: "success",
    requested_place_id: "126508",
    place_card: card({ photos: [], thumbnail_url: "https://example.test/found.jpg" }),
  });
  render(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ image_url: null })}
      onClose={() => {}}
    />,
    { wrapper: TripProvider },
  );

  expect(await screen.findByRole("img", { name: "경복궁 이미지" })).toBeInTheDocument();
  expect(screen.getByTestId("photo-strip-slot")).toBeInTheDocument();
});

it("미리 알 수 없는 경로(사진 유사 검색·지난 추천)는 종전대로 자리를 잡아 둔다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );

  // item도 card도 없으면 판단 근거가 없다 — 접었다 펴는 것보다 잡아 두는 쪽이 낫다.
  expect(screen.getByTestId("photo-strip-slot")).toBeInTheDocument();
});

it("카드에 이미지가 없어도 상세 조회 실패는 알린다", async () => {
  mockedFetch.mockResolvedValue({
    status: "unavailable",
    requested_place_id: "126508",
    place_card: null,
  });
  render(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ image_url: null })}
      onClose={() => {}}
    />,
    { wrapper: TripProvider },
  );

  // 사진이 없는 것과 못 불러온 것은 다르다. 오류는 자리를 차지하더라도 보여준다.
  expect(await screen.findByText("상세 정보를 불러오지 못했어요.")).toBeInTheDocument();
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

/*
 * 로딩 자리를 회색 덩어리 하나로 두면 중앙값 0.73초·p90 1.44초(2026-09-05 실측)를
 * 그 상태로 버티게 되고, 값이 도착하는 순간 표가 통째로 나타나 화면이 한 번 튄다.
 * 완성됐을 때와 같은 줄 모양으로 두어 값만 차오르게 한다.
 */
it("상세를 기다리는 동안 표와 같은 줄 모양 스켈레톤을 그린다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );

  const skeleton = screen.getByRole("status");
  expect(within(skeleton).getByText("장소 상세 정보를 불러오는 중")).toBeInTheDocument();
  // 완성된 표의 중앙값이 4줄이라 그만큼 잡아 둔다(8,060곳 실측).
  expect(screen.getAllByTestId("info-skeleton-row")).toHaveLength(4);
});

/*
 * 줄 수는 처음부터 최종값이고, 200ms 지연은 회색 바에만 걸린다.
 *
 * 줄 수를 지연에 묶으면 200ms 지점에 표가 1줄(또는 0줄)에서 4줄로 커지면서 개요·
 * 추천 이유 같은 아래 내용이 통째로 밀린다. 지연의 목적("조회가 빨라지면 번쩍이지
 * 않게")은 움직이는 바를 늦추는 것으로 그대로 지켜진다.
 */
it("지연 200ms 동안에도 줄 자리는 그대로 두고 회색 바만 감춘다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );

  const rowsBefore = screen.getAllByTestId("info-skeleton-row").length;
  expect(rowsBefore).toBe(4);
  // 지연 중에는 바가 자리만 차지하고 보이지 않는다.
  for (const bar of screen.getAllByTestId("info-skeleton-bar")) {
    expect(bar).toHaveClass("invisible");
  }

  await waitFor(() => {
    expect(screen.getAllByTestId("info-skeleton-bar")[0]).not.toHaveClass("invisible");
  });

  // 바가 켜져도 줄 수는 그대로다 — 이것이 밀림의 직접 원인이었다.
  expect(screen.getAllByTestId("info-skeleton-row")).toHaveLength(rowsBefore);
});

it("item이 없는 경로에서도 표 자리를 처음부터 잡는다", async () => {
  /* 사진 유사 검색·지난 추천은 이름과 place_id만 넘기고 연다. 아는 운영시간이
     없어서 예전에는 지연이 끝날 때까지 상자 자체가 없었고, 200ms에 상자째
     나타나며 아래가 밀렸다. */
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );

  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.getAllByTestId("info-skeleton-row")).toHaveLength(4);
});

/* 운영시간은 추천 카드에서 이미 아는 값이라 그 줄만 진짜로 채워져 있다. */
it("운영시간을 이미 알면 스켈레톤을 한 줄 적게 그린다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  const { rerender } = render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );
  await screen.findByRole("status");
  expect(screen.getAllByTestId("info-skeleton-row")).toHaveLength(4);

  rerender(
    <RecommendationDetailPreviewModal
      item={recommendationItem({ operating_hours_display: "09:00~18:00" })}
      onClose={() => {}}
    />,
  );

  await screen.findByText("09:00~18:00 · 영업 중");
  expect(screen.getAllByTestId("info-skeleton-row")).toHaveLength(3);
  // 운영시간 줄과 스켈레톤이 같은 상자에 있어야 값이 도착할 때 상자 수가 안 바뀐다.
  const skeletonBox = screen.getByRole("status");
  expect(within(skeletonBox).getByText("09:00~18:00 · 영업 중")).toBeInTheDocument();
});

it("상세가 도착하면 스켈레톤이 사라지고 실제 표가 남는다", async () => {
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
  expect(await screen.findByRole("status")).toBeInTheDocument();

  resolveDetail({
    status: "success",
    requested_place_id: "126508",
    place_card: card({ parking: "가능 (240대)" }),
  });

  expect(await screen.findByText("가능 (240대)")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

/*
 * 길찾기 버튼은 스크롤 영역 바깥의 하단 고정 바다. 늦게 생기면 그만큼 본문
 * 높이가 줄며 읽던 자리가 밀린다 — 자리는 먼저 잡되 누르지는 못하게 한다.
 */
it("상세를 기다리는 동안 길찾기 버튼 자리를 잡되 누를 수 없다", async () => {
  seedDeviceLocation();
  mockedFetch.mockReturnValue(new Promise(() => {}));
  const user = userEvent.setup();
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );

  const button = await screen.findByRole("button", { name: /네이버 지도로 길찾기/ });
  expect(button).toBeDisabled();

  // 목적지 좌표가 상세 응답에 실려 오므로 그 전에는 열 지도가 없다.
  await user.click(button);
  expect(mockedDirections).not.toHaveBeenCalled();
});

it("상세가 도착하면 길찾기 버튼이 활성화된다", async () => {
  seedDeviceLocation();
  let resolveDetail!: (value: RecommendationPlaceDetailResponse) => void;
  mockedFetch.mockReturnValue(
    new Promise((resolve) => {
      resolveDetail = resolve;
    }),
  );
  const user = userEvent.setup();
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );
  expect(await screen.findByRole("button", { name: /네이버 지도로 길찾기/ })).toBeDisabled();

  resolveDetail({
    status: "success",
    requested_place_id: "126508",
    place_card: card({ latitude: 37.5796, longitude: 126.977 }),
  });

  const button = await screen.findByRole("button", { name: /네이버 지도로 길찾기/ });
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
  expect(mockedDirections).toHaveBeenCalledWith(
    expect.objectContaining({ destLat: 37.5796, destLng: 126.977 }),
  );
});

/* 현재 위치가 없으면 상세가 와도 버튼은 끝내 안 나온다 — 자리를 잡으면 영영 못
   누르는 버튼을 보여주게 된다. */
it("현재 위치가 없으면 로딩 중에도 버튼 자리를 잡지 않는다", async () => {
  mockedFetch.mockReturnValue(new Promise(() => {}));
  render(
    <RecommendationDetailPreviewModal placeId="126508" placeName="경복궁" onClose={() => {}} />,
    { wrapper: TripProvider },
  );

  await screen.findByRole("status");
  expect(screen.queryByRole("button", { name: /네이버 지도로 길찾기/ })).not.toBeInTheDocument();
});

/*
 * 스켈레톤 행과 실제 행이 같은 뼈대(InfoRowShell)에서 나와야 값이 도착할 때 표
 * 높이가 그대로다. 한때 두 곳에 따로 적혀 있어 스켈레톤이 7px 낮았고, 표가 그만큼
 * 늘어나며 아래 내용이 밀렸다. jsdom은 실제 높이를 재지 못하므로 뼈대가 같은지로
 * 지킨다.
 */
it("스켈레톤 행과 실제 행이 같은 뼈대를 쓴다", async () => {
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

  await screen.findByRole("status");
  const skeletonRowClass = screen.getAllByTestId("info-skeleton-row")[0].className;

  resolveDetail({
    status: "success",
    requested_place_id: "126508",
    place_card: card({ parking: "가능 (240대)" }),
  });

  const realRow = (await screen.findAllByTestId("info-row"))[0];
  expect(realRow.className).toBe(skeletonRowClass);
});
