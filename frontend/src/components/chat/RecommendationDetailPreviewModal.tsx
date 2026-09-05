/*
 * 역할: 추천/INFO 카드 클릭 시 C PlaceDetails를 모달로 표시한다.
 * 입력: D 추천 결과(거리·운영시간) 또는 INFO가 이미 받은 InfoPlaceCard.
 * 출력: 모달의 썸네일·개요·운영·휴무·주차·요금·편의시설.
 * 호출 시점: RecommendationResultMessage의 추천 카드 클릭.
 */

import { motion } from "framer-motion";
import {
  Accessibility,
  Armchair,
  Baby,
  Bath,
  CalendarOff,
  Car,
  Clock,
  CreditCard,
  Dog,
  Eye,
  Loader2,
  type LucideIcon,
  MapPin,
  Milk,
  MoveVertical,
  Navigation,
  PawPrint,
  Sparkles,
  SquareParking,
  Wallet,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { fetchRecommendationPlaceDetails } from "../../api/trip";
import { useTripState } from "../../state/TripContext";
import type { InfoPlaceCard, RecommendationItem } from "../../types";
import { openNaverDirections, openNaverMapSearch } from "../../utils/naverDirections";
import {
  groupSubwayArrivals,
  parseSubwayArrival,
  subwayLineColor,
} from "../../utils/subwayDisplay";
import { travelShortLabel } from "../../utils/travelDisplay";
import {
  ConcentrationForecastBars,
  PopulationForecastBars,
  RoadTrafficStatusSection,
} from "./CongestionForecastBars";

interface RecommendationDetailPreviewModalProps {
  /** 추천 카드에서 열면 현재 거리·운영시간과 함께 C 상세를 추가 조회한다. */
  item?: RecommendationItem;
  /** INFO 카드에서 열면 답변 요약을 즉시 표시한다. */
  card?: InfoPlaceCard;
  /**
   * 사진 검색 결과에서 열 때. 그 결과는 content_id와 유사도뿐이라 위 두 모양을
   * 만들 수 없어, 조회에 필요한 최소값만 받는다.
   */
  placeId?: string;
  placeName?: string;
  onClose: () => void;
}

/**
 * 주소·혼잡도·행사 INFO는 첫 응답에서 필요한 값만 받아온다. 카드 클릭 때만
 * 전체 PlaceDetails를 보강 조회해, 답변 단계의 불필요한 상세 API 호출은 피한다.
 */
function needsDetailEnrichment(card: InfoPlaceCard | undefined): boolean {
  // 실시간 도시데이터 INFO는 이미 지역 단위 상세·지도 링크를 응답에 실었다.
  // 관광 PlaceDetails를 다시 조회하면 이 값을 덮어써 모달의 실시간 근거가 사라진다.
  if (card?.realtime_map_url || (card?.realtime_detail_items?.length ?? 0) > 0) return false;
  return Boolean(card && ["location_info", "concentration", "event"].includes(card.question_type));
}

/** Figma "PlaceDetail (Sheet)"(29:180)의 InfoTable 행 순서·아이콘. */
const INFO_TABLE_FIELDS: Array<[keyof InfoPlaceCard, string, string, LucideIcon]> = [
  ["operating_hours", "운영시간", "Hours", Clock],
  ["rest_date", "휴무일", "Closed on", CalendarOff],
  ["fee", "요금", "Admission", Wallet],
  ["parking", "주차", "Parking", Car],
  ["parking_fee", "주차 요금", "Parking fee", Wallet],
  ["baby_carriage", "유모차", "Stroller rental", Baby],
  ["pet", "반려동물 동반", "Pets allowed", PawPrint],
  ["credit_card", "카드 결제", "Card payment", CreditCard],
  ["restroom", "화장실", "Restroom", Bath],
];

/*
 * 편의시설 구획의 행 순서·아이콘. 출처는 무장애 여행 정보(D-077)지만 화면에는
 * 그 말을 쓰지 않는다 — 읽는 사람에게는 제도 용어보다 "편의시설"이 바로 읽힌다.
 * 채움률이 높은 것부터 둔다(원문이 있는 장소 기준: 장애인 화장실 48% → 보조견 9%).
 *
 * 접근로·주출입구는 넣지 않는다. 원문이 대부분 단차·경사 서술이라 카드에서
 * 다루지 않기로 했다 — 그 값은 "휠체어로 들어갈 수 있나요" 질문의 답변
 * (answer_fields의 wheelchair_access)으로만 나간다.
 *
 * 유모차는 두 줄이 아니라 한 줄이다. 무장애 원문이 있으면 stroller_rental이
 * 차고 위 표의 baby_carriage가 비므로, 두 표에 한 줄씩 두어도 함께 보이지 않는다.
 */
const ACCESSIBILITY_FIELDS: Array<[keyof InfoPlaceCard, string, string, LucideIcon]> = [
  ["accessible_restroom", "장애인 화장실", "Accessible restroom", Bath],
  ["accessible_parking", "장애인 주차", "Accessible parking", SquareParking],
  ["elevator", "승강기", "Elevator", MoveVertical],
  ["visual_guide", "시각 안내", "Visual guidance", Eye],
  ["wheelchair_rental", "휠체어 대여", "Wheelchair rental", Accessibility],
  ["nursing_room", "수유·기저귀", "Nursing & diaper", Milk],
  ["seating", "의자식 좌석", "Chair seating", Armchair],
  ["stroller_rental", "유모차 대여", "Stroller rental", Baby],
  ["guide_dog", "보조견 동반", "Guide dogs allowed", Dog],
];

/**
 * "영업 중"/"운영 종료" 표시는 실시간으로 계산된 값이 있을 때만 붙인다.
 * detailCard.operating_hours는 원문 텍스트일 뿐 개장 여부를 담지 않는다 —
 * 그 판정은 item.remaining_minutes(D가 계산)로만 할 수 있다. item 없이 연
 * INFO·사진 검색 경로에서는 근거 없이 "영업 중"을 지어내지 않는다.
 */
function operatingStatusSuffix(item: RecommendationItem | undefined, isEn: boolean): string | null {
  if (!item) return null;
  if (isEn) return item.remaining_minutes === null ? "Closed" : "Open";
  return item.remaining_minutes === null ? "운영 종료" : "영업 중";
}

const SEOUL_PARKING_PORTAL_URL = "https://parking.seoul.go.kr/";

const ANSWER_FIELD_LABELS: Record<string, string> = {
  address: "주소",
  concentration: "혼잡도",
  event: "행사",
  "상권 지역": "상권 지역",
  "상권 기준": "상권 기준",
  업종: "업종",
  "실시간 활동": "실시간 활동",
  "기준 시각": "기준 시각",
  안내: "안내",
  homepage: "홈페이지",
  operating_hours: "운영시간",
  rest_date: "휴무일",
  parking: "주차",
  parking_fee: "주차 요금",
  fee: "요금",
  baby_carriage: "유모차",
  pet: "반려동물 동반",
  credit_card: "카드 결제",
  restroom: "화장실",
};

/*
 * 서버가 내려주는 필드는 대부분 한국어 자유 텍스트라 전부 옮길 수 없다. 다만
 * 필드 "이름"(키) 자체는 백엔드 스키마에 고정돼 있어 항상 같은 항목만 나온다 —
 * 이 목록에 있는 것만 영어 라벨로 바꾸고, 나머지(상권 지역 등 자유 키)는
 * 한국어 그대로 둔다.
 */
const ANSWER_FIELD_LABELS_EN: Record<string, string> = {
  address: "Address",
  concentration: "Crowd level",
  event: "Event",
  homepage: "Website",
  operating_hours: "Hours",
  rest_date: "Closed on",
  parking: "Parking",
  parking_fee: "Parking fee",
  fee: "Admission",
  baby_carriage: "Stroller rental",
  pet: "Pets allowed",
  credit_card: "Card payment",
  restroom: "Restroom",
};

function formatDetailValue(key: keyof InfoPlaceCard, value: string): string {
  let formatted = value.replace(/\s*※\s*/g, "\n※ ");
  if (key === "fee") formatted = formatted.replace(/(?:^|\s)-\s*/g, "\n- ");
  return formatted.trim();
}

function DetailText({ fieldKey, value }: { fieldKey: keyof InfoPlaceCard; value: string }) {
  // ※로 시작하는 TourAPI 예외·보충 안내는 핵심 값과 중요도가 다르다. 모든 상세
  // 모달이 이 컴포넌트를 거치므로 추천 카드와 INFO 카드의 가독성도 함께 맞춰진다.
  const lines = formatDetailValue(fieldKey, value).split("\n");
  return (
    <div className="space-y-1">
      {lines.map((line, index) =>
        line.startsWith("※") ? (
          <p key={`${line}-${index}`} className="pt-1 text-xs leading-5 text-muted">
            {line}
          </p>
        ) : (
          <p key={`${line}-${index}`} className="whitespace-pre-line text-ink">
            {line}
          </p>
        ),
      )}
    </div>
  );
}

interface OperatingHoursRow {
  period: string;
  hours: string;
}

function parseOperatingHours(value: string): OperatingHoursRow[] | null {
  // TourAPI 원문은 "[기간]시간[기간]시간"처럼 구분자 없이 이어지는 경우가 있다.
  const rows = Array.from(value.matchAll(/\[([^\]]+)\]\s*-?\s*(.*?)(?=\[|$)/g))
    .map(([, period, hours]) => ({
      period: period.trim().split("/").join(" · "),
      hours: hours
        .trim()
        .replace(/(\d{2}:\d{2})\s*~\s*(\d{2}:\d{2})/g, "$1–$2")
        .replace(/\(\s*입장\s*마감\s*([^)]+)\)/g, "· 입장 마감 $1")
        .replace(/\s{2,}/g, " "),
    }))
    .filter(({ period, hours }) => period && hours);
  return rows.length > 0 ? rows : null;
}

function OperatingHoursRows({ rows }: { rows: OperatingHoursRow[] }) {
  return (
    <div className="mt-1 grid gap-2">
      {rows.map(({ period, hours }) => (
        <div key={period} className="rounded-lg border border-border bg-bg px-3 py-2 text-left">
          <p className="text-xs font-semibold text-ink">{period}</p>
          <p className="mt-0.5 text-sm text-ink">{hours}</p>
        </div>
      ))}
    </div>
  );
}

/**
 * InfoTable 한 줄의 뼈대. 스켈레톤 행도 이것을 쓴다.
 *
 * 여백과 정렬을 한 곳에만 두는 것이 요점이다. 두 곳에 따로 적어 두었더니 스켈레톤
 * 행이 실제 행보다 7px 낮았고(내용 높이 15px 대 22px), 값이 도착할 때 표 전체가
 * 그만큼 늘어났다.
 */
function InfoRowShell({
  left,
  right,
  rightClassName = "text-ink",
  testId,
  decorative,
}: {
  left: ReactNode;
  right: ReactNode;
  rightClassName?: string;
  testId?: string;
  decorative?: boolean;
}) {
  return (
    <div
      data-testid={testId}
      aria-hidden={decorative}
      className="flex items-start justify-between gap-3 py-3"
    >
      <div className="flex shrink-0 items-center gap-2 pt-0.5">{left}</div>
      <div className={`min-w-0 flex-1 text-right text-sm ${rightClassName}`}>{right}</div>
    </div>
  );
}

/** InfoTable 한 줄. 로딩 중 미리보기 행도 같은 모양을 써서 실제 값으로 바뀔 때 자리가 흔들리지 않는다. */
function InfoRow({
  icon: Icon,
  label,
  emphasized,
  children,
}: {
  icon: LucideIcon;
  label: string;
  emphasized?: boolean;
  children: ReactNode;
}) {
  return (
    <InfoRowShell
      testId="info-row"
      left={
        <>
          <Icon size={15} className="text-muted" />
          <span className="text-sm text-ink">{label}</span>
        </>
      }
      rightClassName={emphasized ? "font-bold text-brand" : "text-ink"}
      right={children}
    />
  );
}

/** Figma InfoTable(29:203) — 아이콘+라벨 / 값을 한 줄씩, 실선으로 나눈다. */
function InfoTable({
  card,
  item,
  isEn,
}: {
  card: InfoPlaceCard;
  item?: RecommendationItem;
  isEn: boolean;
}) {
  const visibleEntries = INFO_TABLE_FIELDS.filter(([key]) => {
    const value = card[key];
    return typeof value === "string" && value.trim();
  });
  if (visibleEntries.length === 0) return null;

  return (
    <div className={INFO_CARD_BOX}>
      <div className={INFO_CARD_ROWS}>
        {visibleEntries.map(([key, labelKo, labelEn, Icon]) => {
          const value = card[key];
          if (typeof value !== "string") return null;
          const operatingHours = key === "operating_hours" ? parseOperatingHours(value) : null;
          const statusSuffix = key === "operating_hours" ? operatingStatusSuffix(item, isEn) : null;
          return (
            <InfoRow
              key={key}
              icon={Icon}
              label={isEn ? labelEn : labelKo}
              emphasized={Boolean(statusSuffix)}
            >
              {operatingHours ? (
                <OperatingHoursRows rows={operatingHours} />
              ) : statusSuffix ? (
                `${value} · ${statusSuffix}`
              ) : (
                <DetailText fieldKey={key} value={value} />
              )}
            </InfoRow>
          );
        })}
      </div>
    </div>
  );
}

/**
 * 편의시설 구획. 값이 있는 항목만 그리고, 아홉 개가 모두 비면 제목까지 숨긴다.
 *
 * 빈 항목을 "없음"으로 그리지 않는 것이 이 구획의 전제다. 이 데이터는 있으면 적고
 * 없으면 비우는 식이라(없다고 답한 값은 장애인 화장실 4건뿐), 빈 값을 없음으로
 * 읽으면 있는 시설을 없다고 말하게 된다.
 */
function AccessibilityTable({ card, isEn }: { card: InfoPlaceCard; isEn: boolean }) {
  const visibleEntries = ACCESSIBILITY_FIELDS.filter(([key]) => {
    const value = card[key];
    return typeof value === "string" && value.trim();
  });
  if (visibleEntries.length === 0) return null;

  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-xs font-bold text-label">{isEn ? "Facilities" : "편의시설"}</h3>
      <div className={INFO_CARD_BOX}>
        <div className={INFO_CARD_ROWS}>
          {visibleEntries.map(([key, labelKo, labelEn, Icon]) => {
            const value = card[key];
            if (typeof value !== "string") return null;
            return (
              <InfoRow key={key} icon={Icon} label={isEn ? labelEn : labelKo}>
                <DetailText fieldKey={key} value={value} />
              </InfoRow>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/**
 * 스켈레톤을 띄울지 정한다. 로딩이 시작돼도 delayMs 동안은 띄우지 않는다.
 *
 * 최소 노출 시간은 두지 않는다. 2026-09-05 실측에서 이 조회(/chat/place-details)는
 * 표본 24건이 모두 0.5초를 넘었고(중앙값 0.73초, p90 1.44초) 200ms 안에 끝난 건이
 * 하나도 없었다 — "떴다가 곧바로 사라져 번쩍이는" 상황이 지금 분포에서는 생기지
 * 않는다. 최소 노출을 두면 이득 없이 이미 받은 값을 늦추기만 한다.
 *
 * 그래도 지연을 남기는 이유는 이 값이 서버 상태에 달려 있어서다. 나중에 상세를
 * 캐시하거나 응답이 빨라지면 그때 번쩍임이 생기는데, 그 안전장치를 미리 둔다.
 */
function useDelayedSkeleton(isLoading: boolean, delayMs = 200): boolean {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!isLoading) {
      setVisible(false);
      return;
    }
    const timer = setTimeout(() => setVisible(true), delayMs);
    return () => clearTimeout(timer);
  }, [isLoading, delayMs]);

  return visible;
}

/* 완성된 표가 몇 줄인지의 실측 분포(8,060곳, 2026-09-05).
 *
 *   0줄 1.1% · 1줄 1.0% · 2줄 11.4% · 3줄 22.1% · 4줄 30.0% · 5줄 33.1% ·
 *   6줄 0.9% · 7줄 0.3%
 *
 * 스켈레톤을 중앙값인 4줄로 잡는다. 늘어나든 줄어들든 그만큼 아래 내용이
 * 움직이므로, 어느 쪽으로도 적게 어긋나는 값이 낫다 — 평균 어긋남이 3줄로 잡으면
 * 1.17줄, 4줄로 잡으면 0.88줄이다.
 */
const INFO_TABLE_SKELETON_ROWS = 4;

/* 상세 정보 표의 겉 상자와 줄 묶음. 스켈레톤과 실제 표가 같은 값을 써야 값이
 * 도착할 때 상자가 제자리에 그대로 남는다 — 어긋나면 그 차이만큼 화면이 튄다.
 *
 * 교체에 페이드를 넣지 않는다. 스켈레톤은 즉시 사라지는데 새 내용이 투명하게
 * 시작하므로, 무엇을 감싸든 그 사이가 빈다 — 행 사이 가로줄(divide-y)까지 함께
 * 흐려져 오히려 더 눈에 띄었다. 상자·행 높이·가로줄 위치가 모두 같은 지금은
 * 회색 바가 글자로 바뀌는 것 말고는 움직이는 것이 없어, 그대로 바꾸는 편이
 * 조용하다. */
const INFO_CARD_BOX = "rounded-xl bg-white px-4 shadow-resting";
const INFO_CARD_ROWS = "flex flex-col divide-y divide-border";

/**
 * 상세를 기다리는 동안의 InfoTable 자리. 완성됐을 때와 같은 줄 모양으로 둔다.
 *
 * 높이만 잡은 회색 덩어리를 쓰지 않는 이유는 중앙값 0.73초·p90 1.44초를 그 상태로
 * 버텨야 하기 때문이다. 덩어리는 그동안 멈춘 것처럼 보이고, 값이 채워지는 순간
 * 표가 통째로 나타나 화면이 한 번 튄다.
 *
 * 값 자리의 너비를 줄마다 다르게 둔 것도 같은 이유다. 폭이 같으면 글자가 아니라
 * 표로 읽힌다.
 *
 * 이미 아는 운영시간(leadingRow)은 별도 상자가 아니라 이 상자의 첫 줄로 받는다.
 * 상자를 따로 두면 값이 도착할 때 흰 상자가 둘에서 하나로 줄며 그 사이 간격까지
 * 사라져, 줄 수를 아무리 맞춰도 화면이 한 번 접힌다.
 */
function InfoTableSkeleton({
  rows,
  isEn,
  leadingRow,
  showBars = true,
}: {
  rows: number;
  isEn: boolean;
  leadingRow?: ReactNode;
  /*
   * 거짓이면 줄 자리는 그대로 두고 회색 바만 감춘다(useDelayedSkeleton의 첫 200ms).
   *
   * 줄 수를 지연에 묶으면 200ms 지점에 표가 커지면서 아래 내용이 통째로 밀린다 —
   * 아는 값이 있으면 1줄에서 4줄로, 없으면 상자째 나타난다. 높이를 만드는 것은
   * 바깥 h-5 껍데기이므로, 바를 invisible로 두면 자리는 유지한 채 조용해진다.
   *
   * 지연의 목적도 그대로 지킨다. 주석이 말하는 "떴다가 곧바로 사라져 번쩍이는"
   * 것은 움직이는 회색 바이고, 그것은 여전히 200ms 뒤에만 나타난다.
   */
  showBars?: boolean;
}) {
  const valueWidths = ["w-[70%]", "w-[45%]", "w-[60%]"];
  const barVisibility = showBars ? "" : " invisible";

  return (
    <div role="status" className={INFO_CARD_BOX}>
      <div className={INFO_CARD_ROWS}>
        {leadingRow}
        {Array.from({ length: rows }, (_, index) => (
          /*
           * 바를 감싼 h-5는 글자 한 줄(text-sm의 줄 높이 20px)이 차지하는 자리다.
           * 바 자체 높이(14px)만 두면 행이 그만큼 낮아져, 값이 도착할 때 표가 늘어난다.
           */
          <InfoRowShell
            key={index}
            testId="info-skeleton-row"
            decorative
            left={
              <>
                <span
                  className={`h-[15px] w-[15px] animate-pulse rounded bg-chip${barVisibility}`}
                />
                <span className="flex h-5 items-center">
                  <span className={`h-3.5 w-14 animate-pulse rounded bg-chip${barVisibility}`} />
                </span>
              </>
            }
            right={
              <span className="flex h-5 items-center justify-end">
                <span
                  data-testid="info-skeleton-bar"
                  className={`h-3.5 animate-pulse rounded bg-chip ${valueWidths[index % valueWidths.length]}${barVisibility}`}
                />
              </span>
            }
          />
        ))}
      </div>
      <span className="sr-only">
        {isEn ? "Loading place details" : "장소 상세 정보를 불러오는 중"}
      </span>
    </div>
  );
}

/**
 * 상세 조회가 끝나기 전, 이미 아는 값만 먼저 보여준다.
 *
 * 운영시간은 추천 카드를 만들 때 D가 이미 계산해 item.operating_hours_display에
 * 실어 보낸 값이다(PlaceCard가 목록에서 쓰는 것과 같은 값) — 상세 조회
 * (fetchRecommendationPlaceDetails)가 끝나야만 보이던 것을, 이미 갖고 있던 값으로
 * 먼저 그린다. 그 값이 없으면(INFO·사진 검색 경로처럼 item 자체가 없는 경우) 아무것도
 * 그리지 않는다 — 근거 없이 지어내지 않는다는 operatingStatusSuffix와 같은 원칙이다.
 */
function QuickInfoPreview({ item, isEn }: { item?: RecommendationItem; isEn: boolean }) {
  if (!item?.operating_hours_display) return null;
  const statusSuffix = operatingStatusSuffix(item, isEn);
  return (
    <InfoRow icon={Clock} label={isEn ? "Hours" : "운영시간"} emphasized={Boolean(statusSuffix)}>
      {statusSuffix
        ? `${item.operating_hours_display} · ${statusSuffix}`
        : item.operating_hours_display}
    </InfoRow>
  );
}

function sourceLabel(sourceType: string): string {
  if (sourceType === "google_review") return "Google 리뷰";
  if (sourceType === "naver_post") return "네이버 블로그";
  if (sourceType === "tour_overview") return "관광공사 장소 정보";
  return "방문자 후기";
}

function PreferenceInsightsSection({ card }: { card: InfoPlaceCard }) {
  const insights = card.preference_insights ?? [];
  if (insights.length === 0) return null;

  return (
    <section className="rounded-xl border border-blue-100 bg-blue-50/50 p-4 dark:border-blue-950/70 dark:bg-blue-950/20">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            방문자 후기에 나타난 특징
          </h3>
          <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-300">
            같은 문서에서 반복된 표현은 한 번만 집계했어요.
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {insights.map((insight, index) => {
          return (
            <details
              key={insight.code}
              open={index === 0}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2 dark:border-gray-700 dark:bg-gray-900"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                <p className="min-w-0 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {insight.label}
                  <span className="ml-2 text-xs font-medium text-blue-600 dark:text-blue-300">
                    {insight.mention_count}개 후기
                  </span>
                </p>
              </summary>

              <div className="mt-2 space-y-3 border-t border-gray-100 pt-2.5 dark:border-gray-800">
                {insight.evidence.map((evidence, evidenceIndex) => (
                  <blockquote
                    key={`${evidence.text}-${evidenceIndex}`}
                    className="border-l-2 border-blue-300 pl-3 text-sm leading-6 text-gray-700 dark:text-gray-300"
                  >
                    <p>“{evidence.text}”</p>
                    <EvidenceSource evidence={evidence} />
                  </blockquote>
                ))}
                {insight.evidence.length === 0 && (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    대표 문장을 준비하고 있어요.
                  </p>
                )}
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

function EvidenceSource({
  evidence,
}: {
  evidence: NonNullable<InfoPlaceCard["preference_insights"]>[number]["evidence"][number];
}) {
  const label = sourceLabel(evidence.source_type);
  return evidence.source_url ? (
    <a
      href={evidence.source_url}
      target="_blank"
      rel="noreferrer"
      className="mt-1 inline-block text-xs font-medium text-blue-700 hover:underline dark:text-blue-300"
    >
      {label} ↗
    </a>
  ) : (
    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{label}</p>
  );
}

// www.로 시작하는 프로토콜 없는 도메인도 잡는다(실측: TourAPI homepage 필드의
// 3.6%가 이 형태 — "www.kh.or.kr"처럼 http(s):// 없이 온다). 일반 도메인 정규식은
// 숫자·단위 표기(예: "3.5km")를 오탐할 수 있어 www. 접두만 좁게 잡는다.
const URL_PATTERN = /(https?:\/\/[^\s]+|www\.[^\s]+)/g;

function isLinkable(part: string): boolean {
  return /^(https?:\/\/|www\.)/.test(part);
}

function toHref(part: string): string {
  // www.만 있으면 상대경로로 오인돼 우리 사이트 안의 없는 페이지로 이동한다.
  return part.startsWith("www.") ? `https://${part}` : part;
}

/** "관련 정보" 값 안의 URL(http(s) 또는 www.)을 클릭 가능한 링크로 만든다. */
function AnswerValue({ value }: { value: string }) {
  const parts = value.split(URL_PATTERN);
  return (
    <dd className="whitespace-pre-line text-gray-900 dark:text-gray-100">
      {parts.map((part, index) =>
        isLinkable(part) ? (
          <a
            key={index}
            href={toHref(part)}
            target="_blank"
            rel="noreferrer"
            className="break-all text-blue-600 underline hover:text-blue-700 dark:text-blue-400"
          >
            {part}
          </a>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </dd>
  );
}

type RealtimeDetailItem = NonNullable<InfoPlaceCard["realtime_detail_items"]>[number];
type ParkingTab = "전체" | "공영" | "민영" | "기타";

interface ParkingCardItem {
  item: RealtimeDetailItem;
  category: Exclude<ParkingTab, "전체">;
  availableSpaces: number | null;
  capacity: number | null;
  currentParkedCount: number | null;
}

function isRealtimeParkingCard(card: InfoPlaceCard): boolean {
  return ["realtime_parking", "realtime_public_parking"].includes(card.question_type);
}

function isRealtimeSubwayCard(card: InfoPlaceCard): boolean {
  return card.question_type === "realtime_subway";
}

function SubwayModalArrivalRow({ item }: { item: RealtimeDetailItem }) {
  const { arrival } = parseSubwayArrival(item.subtitle ?? "");
  const arrivalKnown = arrival !== null && !arrival.includes("미제공");
  const destination = item.details["종착역"] ? `${item.details["종착역"]}행` : "행선지 정보 미제공";
  return (
    <div className="flex min-w-0 items-center justify-between gap-2">
      <span className="min-w-0 truncate text-sm text-ink">{destination}</span>
      {arrival && (
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${
            arrivalKnown ? "bg-emerald-50 text-emerald-700" : "bg-white text-muted"
          }`}
        >
          {arrival}
        </span>
      )}
    </div>
  );
}

function RealtimeSubwayEntries({ card }: { card: InfoPlaceCard }) {
  const items = card.realtime_detail_items ?? [];
  const groups = groupSubwayArrivals(items);
  return (
    <section className="rounded-xl border border-border bg-chip/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">실시간 지하철 도착 정보</h3>
          <p className="mt-0.5 text-xs text-muted">
            {card.realtime_area_name ?? "가까운 역"}
            {card.realtime_observed_at ? ` · ${card.realtime_observed_at} 기준` : ""}
          </p>
        </div>
        <RealtimeDetailLinks card={card} />
      </div>
      <div className="mt-3 grid gap-3">
        {groups.map((group) => (
          <article
            key={group.stationLine}
            className="min-w-0 rounded-lg border border-border bg-white px-3 py-2.5"
          >
            <div className="flex min-w-0 items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: subwayLineColor(group.stationLine) }}
                aria-hidden="true"
              />
              <span
                className="min-w-0 truncate text-sm font-bold text-ink"
                title={group.stationLine}
              >
                {group.stationLine}
              </span>
            </div>
            {/* 같은 역·같은 호선이라도 상행/하행은 다른 방향이라 칸을 나눠 보여준다
                (2026-09-02 실사용 지적) — 나열 순서만으로는 구분이 안 됐다. */}
            <div
              className={`mt-2 grid gap-2 ${group.directions.length > 1 ? "sm:grid-cols-2" : "grid-cols-1"}`}
            >
              {group.directions.map((direction) => (
                <div key={direction.direction} className="min-w-0 rounded-lg bg-chip px-2.5 py-2">
                  <p className="text-xs font-semibold text-muted">{direction.direction}</p>
                  <div className="mt-1 grid gap-1">
                    {direction.items.map((item, index) => (
                      <SubwayModalArrivalRow key={`${item.title}-${index}`} item={item} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </article>
        ))}
        {items.length === 0 && (
          <p className="rounded-lg bg-white px-3 py-4 text-center text-sm text-muted">
            지하철 도착 정보를 제공하지 않는 역이에요.
          </p>
        )}
      </div>
    </section>
  );
}

function extractParkingCount(value: string | undefined): number | null {
  const matched = value?.match(/\d[\d,]*/);
  return matched ? Number(matched[0].replaceAll(",", "")) : null;
}

function extractParkingCountFromSubtitle(
  subtitle: string | null | undefined,
  labels: string[],
): number | null {
  if (!subtitle) return null;
  for (const label of labels) {
    const matched = subtitle.match(new RegExp(`${label}\\s*([\\d,]+)\\s*(?:대|면)?`));
    if (matched) return Number(matched[1].replaceAll(",", ""));
  }
  return null;
}

function toParkingCardItem(item: RealtimeDetailItem, questionType: string): ParkingCardItem {
  const type = item.details["유형"];
  const category: Exclude<ParkingTab, "전체"> =
    type === "공영" || type === "민영"
      ? type
      : questionType === "realtime_public_parking"
        ? "공영"
        : "기타";
  return {
    item,
    category,
    // 배포 중 백엔드 재시작 전에도 기존 키(잔여 면수/총 주차면)를 읽는다.
    availableSpaces:
      extractParkingCount(item.details["가능 주차"] ?? item.details["잔여 면수"]) ??
      extractParkingCountFromSubtitle(item.subtitle, ["잔여", "가능"]),
    capacity:
      extractParkingCount(item.details["총 주차"] ?? item.details["총 주차면"]) ??
      extractParkingCountFromSubtitle(item.subtitle, ["총"]),
    currentParkedCount:
      extractParkingCount(item.details["현재 주차"]) ??
      extractParkingCountFromSubtitle(item.subtitle, ["현재"]),
  };
}

function formatParkingCount(value: number | null): string {
  return value === null ? "정보 미제공" : `${new Intl.NumberFormat("ko-KR").format(value)}대`;
}

function parkingStatus(item: ParkingCardItem): "여유" | "보통" | "혼잡" | "현황 미제공" {
  if (item.availableSpaces === null || item.capacity === null || item.capacity === 0)
    return "현황 미제공";
  const availableRatio = item.availableSpaces / item.capacity;
  if (availableRatio >= 0.4) return "여유";
  if (availableRatio >= 0.15) return "보통";
  return "혼잡";
}

function parkingStatusClass(status: ReturnType<typeof parkingStatus>): string {
  if (status === "여유")
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300";
  if (status === "보통")
    return "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300";
  if (status === "혼잡") return "bg-rose-100 text-rose-800 dark:bg-rose-950/50 dark:text-rose-300";
  return "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300";
}

function ParkingLotCard({ parkingItem }: { parkingItem: ParkingCardItem }) {
  const { item, availableSpaces, capacity, currentParkedCount } = parkingItem;
  const status = parkingStatus(parkingItem);
  const address = item.details["주소"];

  return (
    <article className="rounded-xl border border-gray-100 bg-white p-3 shadow-sm dark:border-gray-800 dark:bg-gray-900">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <span className="inline-flex rounded-md bg-sky-100 px-1.5 py-0.5 text-[11px] font-semibold text-sky-800 dark:bg-sky-950/50 dark:text-sky-300">
            {parkingItem.category}
          </span>
          <h4 className="mt-1 break-keep text-sm font-semibold leading-5 text-gray-900 dark:text-gray-100">
            {item.title}
          </h4>
          <p
            className="mt-1 truncate text-xs text-gray-500 dark:text-gray-400"
            title={address ?? item.details["거리"] ?? undefined}
          >
            {address ?? item.details["거리"] ?? "주소 정보 미제공"}
          </p>
        </div>
        <span
          className={`shrink-0 whitespace-nowrap rounded-full px-2 py-1 text-xs font-semibold ${parkingStatusClass(status)}`}
        >
          {status}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="min-w-0 rounded-lg bg-sky-50 px-2.5 py-2 dark:bg-sky-950/30">
          <p className="whitespace-nowrap text-[11px] text-sky-700 dark:text-sky-300">가능 주차</p>
          <p className="mt-0.5 text-sm font-bold leading-5 text-gray-900 dark:text-gray-100">
            {availableSpaces === null
              ? "잔여 정보 미제공"
              : `${new Intl.NumberFormat("ko-KR").format(availableSpaces)}대 가능`}
          </p>
        </div>
        <div className="min-w-0 rounded-lg bg-gray-50 px-2.5 py-2 dark:bg-gray-800">
          <p className="whitespace-nowrap text-[11px] text-gray-500 dark:text-gray-400">
            주차 규모
          </p>
          <p className="mt-0.5 text-sm font-bold leading-5 text-gray-900 dark:text-gray-100">
            {capacity === null
              ? "총 대수 미제공"
              : `총 ${new Intl.NumberFormat("ko-KR").format(capacity)}대`}
          </p>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-gray-600 dark:text-gray-300">
        {currentParkedCount !== null && (
          <span className="whitespace-nowrap rounded-full bg-gray-100 px-2 py-1 dark:bg-gray-800">
            {new Intl.NumberFormat("ko-KR").format(currentParkedCount)}대 주차 중
          </span>
        )}
        {item.details["거리"] && (
          <span className="whitespace-nowrap rounded-full bg-gray-100 px-2 py-1 dark:bg-gray-800">
            {item.details["거리"]}
          </span>
        )}
        {item.details["요금"] && (
          <span className="whitespace-nowrap rounded-full bg-gray-100 px-2 py-1 dark:bg-gray-800">
            {item.details["요금"]}
          </span>
        )}
      </div>
      {item.details["기준 시각"] && (
        <p className="mt-2 text-[11px] text-gray-400 dark:text-gray-500">
          {item.details["기준 시각"]} 기준
        </p>
      )}
      {address && (
        <button
          type="button"
          onClick={() => openNaverMapSearch(address)}
          className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 transition-colors hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-300 dark:hover:bg-blue-950/60"
        >
          <span aria-hidden="true">🧭</span>
          네이버 지도로 길찾기
        </button>
      )}
    </article>
  );
}

function RealtimeDetailLinks({ card }: { card: InfoPlaceCard }) {
  return (
    <div className="flex flex-wrap gap-2">
      {card.realtime_source_url && (
        <a
          href={card.realtime_source_url}
          target="_blank"
          rel="noreferrer"
          className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:border-sky-800 dark:bg-gray-900 dark:text-sky-300 dark:hover:bg-sky-900/50"
        >
          서울시 데이터 출처 ↗
        </a>
      )}
      {isRealtimeParkingCard(card) && (
        <a
          href={SEOUL_PARKING_PORTAL_URL}
          target="_blank"
          rel="noreferrer"
          className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:border-sky-800 dark:bg-gray-900 dark:text-sky-300 dark:hover:bg-sky-900/50"
        >
          서울시 실시간 주차정보 ↗
        </a>
      )}
      {card.realtime_map_url && (
        <a
          href={card.realtime_map_url}
          target="_blank"
          rel="noreferrer"
          className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:border-sky-800 dark:bg-gray-900 dark:text-sky-300 dark:hover:bg-sky-900/50"
        >
          실시간 혼잡도 지도 ↗
        </a>
      )}
    </div>
  );
}

function RealtimeParkingEntries({ card }: { card: InfoPlaceCard }) {
  const items = (card.realtime_detail_items ?? []).map((item) =>
    toParkingCardItem(item, card.question_type),
  );
  const [activeTab, setActiveTab] = useState<ParkingTab>("전체");
  const tabs: ParkingTab[] = ["전체", "공영", "민영", "기타"];
  const tabCounts = Object.fromEntries(
    tabs.map((tab) => [
      tab,
      tab === "전체" ? items.length : items.filter((item) => item.category === tab).length,
    ]),
  ) as Record<ParkingTab, number>;
  const visibleItems = items.filter((item) => activeTab === "전체" || item.category === activeTab);
  const visibleRealtimeItems = visibleItems.filter((item) => item.availableSpaces !== null);
  const visibleUnavailableItems = visibleItems.filter((item) => item.availableSpaces === null);
  const realtimeItems = items.filter((item) => item.availableSpaces !== null);
  const totalAvailable = realtimeItems.reduce((sum, item) => sum + (item.availableSpaces ?? 0), 0);
  const totalCapacity = items.reduce((sum, item) => sum + (item.capacity ?? 0), 0);

  return (
    <section className="rounded-2xl border border-sky-100 bg-gradient-to-b from-sky-50 to-white p-4 shadow-sm dark:border-sky-900/60 dark:from-sky-950/30 dark:to-gray-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-wide text-sky-700 dark:text-sky-300">
            REALTIME PARKING
          </p>
          <h3 className="mt-0.5 text-lg font-bold text-gray-900 dark:text-gray-100">주차장 현황</h3>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
            {card.realtime_area_name ?? "가까운 서울시 제공 지역"}
            {card.realtime_observed_at ? ` · ${card.realtime_observed_at} 기준` : ""}
          </p>
        </div>
        <RealtimeDetailLinks card={card} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-blue-600 px-3 py-3 text-white shadow-sm">
          <p className="whitespace-nowrap text-xs font-medium text-blue-100">현재 가능한 주차</p>
          <p className="mt-1 whitespace-nowrap text-xl font-bold">
            {realtimeItems.length > 0
              ? `${new Intl.NumberFormat("ko-KR").format(totalAvailable)}대`
              : "정보 없음"}
          </p>
        </div>
        <div className="rounded-xl border border-sky-100 bg-white px-3 py-3 dark:border-sky-900/60 dark:bg-gray-900">
          <p className="whitespace-nowrap text-xs text-gray-500 dark:text-gray-400">실시간 제공</p>
          <p className="mt-1 whitespace-nowrap text-xl font-bold text-gray-900 dark:text-gray-100">
            {realtimeItems.length}곳
          </p>
        </div>
        <div className="rounded-xl border border-sky-100 bg-white px-3 py-3 dark:border-sky-900/60 dark:bg-gray-900">
          <p className="whitespace-nowrap text-xs text-gray-500 dark:text-gray-400">공영 주차장</p>
          <p className="mt-1 whitespace-nowrap text-xl font-bold text-gray-900 dark:text-gray-100">
            {tabCounts["공영"]}곳
          </p>
        </div>
        <div className="rounded-xl border border-sky-100 bg-white px-3 py-3 dark:border-sky-900/60 dark:bg-gray-900">
          <p className="whitespace-nowrap text-xs text-gray-500 dark:text-gray-400">목록 총 수용</p>
          <p className="mt-1 whitespace-nowrap text-xl font-bold text-gray-900 dark:text-gray-100">
            {formatParkingCount(totalCapacity)}
          </p>
        </div>
      </div>

      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        가능한 주차 대수는 실시간 정보가 제공된 주차장만 합산합니다.
      </p>

      <div className="mt-4 grid grid-cols-4 rounded-xl border border-sky-100 bg-white p-1 dark:border-sky-900/60 dark:bg-gray-900">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            disabled={tabCounts[tab] === 0}
            aria-pressed={activeTab === tab}
            className={`rounded-lg px-2 py-2 text-xs font-semibold transition sm:text-sm ${
              activeTab === tab
                ? "bg-blue-600 text-white shadow-sm"
                : "text-gray-500 hover:bg-sky-50 disabled:cursor-not-allowed disabled:text-gray-300 dark:text-gray-400 dark:hover:bg-sky-950/30"
            }`}
          >
            {tab} {tabCounts[tab]}
          </button>
        ))}
      </div>

      <div className="mt-3 space-y-3">
        {visibleRealtimeItems.length > 0 && (
          <section aria-labelledby="realtime-parking-available-heading">
            <div className="mb-2 flex items-center justify-between">
              <h4
                id="realtime-parking-available-heading"
                className="text-sm font-semibold text-gray-900 dark:text-gray-100"
              >
                실시간 주차 가능
              </h4>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {visibleRealtimeItems.length}곳
              </span>
            </div>
            <div className="space-y-2">
              {visibleRealtimeItems.map((parkingItem, index) => (
                <ParkingLotCard
                  key={`${parkingItem.item.title}-realtime-${index}`}
                  parkingItem={parkingItem}
                />
              ))}
            </div>
          </section>
        )}

        {visibleUnavailableItems.length > 0 && (
          <details
            className="rounded-xl border border-gray-200 bg-gray-50 p-2 dark:border-gray-800 dark:bg-gray-950/40"
            open={visibleRealtimeItems.length === 0}
          >
            <summary className="flex cursor-pointer list-none items-center justify-between rounded-lg px-2 py-2 text-sm font-semibold text-gray-700 hover:bg-white dark:text-gray-200 dark:hover:bg-gray-900">
              <span>실시간 잔여 현황 미제공</span>
              <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                {visibleUnavailableItems.length}곳 보기
              </span>
            </summary>
            <div className="mt-2 space-y-2">
              {visibleUnavailableItems.map((parkingItem, index) => (
                <ParkingLotCard
                  key={`${parkingItem.item.title}-unavailable-${index}`}
                  parkingItem={parkingItem}
                />
              ))}
            </div>
          </details>
        )}
        {visibleItems.length === 0 && (
          <p className="rounded-xl bg-white px-3 py-4 text-center text-sm text-gray-500 dark:bg-gray-900 dark:text-gray-400">
            이 유형의 주차장 정보는 제공되지 않습니다.
          </p>
        )}
      </div>
    </section>
  );
}

function RealtimeDetailEntries({ card }: { card: InfoPlaceCard }) {
  const items = card.realtime_detail_items ?? [];
  if (items.length === 0 && !card.realtime_map_url && !card.realtime_source_url) return null;
  if (isRealtimeParkingCard(card)) return <RealtimeParkingEntries card={card} />;
  if (isRealtimeSubwayCard(card)) return <RealtimeSubwayEntries card={card} />;

  return (
    <section className="rounded-xl border border-sky-100 bg-sky-50/70 p-4 dark:border-sky-900/60 dark:bg-sky-950/20">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            실시간 지역 정보
          </h3>
          <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-300">
            {card.realtime_area_name ?? "가까운 서울시 제공 지역"}
            {card.realtime_observed_at ? ` · ${card.realtime_observed_at} 기준` : ""}
          </p>
        </div>
        <RealtimeDetailLinks card={card} />
      </div>
      {card.realtime_map_url && (
        <iframe
          title={`${card.realtime_area_name ?? "서울시"} 실시간 혼잡도 지도`}
          src={card.realtime_map_url}
          loading="lazy"
          className="mt-3 h-[78vh] min-h-[680px] w-full rounded-lg border border-sky-100 bg-white dark:border-sky-900/60 dark:bg-gray-900"
        />
      )}
      <div className="mt-3 space-y-3">
        {items.map((item, index) => (
          <article
            key={`${item.title}-${index}`}
            className="overflow-hidden rounded-lg border border-sky-100 bg-white dark:border-sky-900/60 dark:bg-gray-900"
          >
            {item.thumbnail_url && (
              <img
                src={item.thumbnail_url}
                alt={`${item.title} 이미지`}
                loading="lazy"
                className="h-36 w-full bg-gray-100 object-cover dark:bg-gray-800"
              />
            )}
            <div className="p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {item.title}
                  </h4>
                  {item.subtitle && (
                    <p className="mt-0.5 text-sm text-sky-700 dark:text-sky-300">{item.subtitle}</p>
                  )}
                </div>
                {item.external_url && (
                  <a
                    href={item.external_url}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 text-xs font-medium text-blue-700 hover:underline dark:text-blue-300"
                  >
                    자세히 보기 ↗
                  </a>
                )}
              </div>
              {Object.keys(item.details).length > 0 && (
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                  {Object.entries(item.details).map(([key, value]) => (
                    <div key={key} className="min-w-0">
                      <dt className="text-gray-500 dark:text-gray-400">{key}</dt>
                      <dd className="mt-0.5 break-words text-gray-800 dark:text-gray-100">
                        {value}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

/*
 * 같은 사진인지 볼 때 http/https 차이는 무시한다.
 *
 * 두 출처가 같은 파일을 스킴만 다르게 가리키는 경우가 있다. `places.first_image_url`은
 * `http`로 적재됐고 `place_image_embeddings.origin_url`은 `https`인 장소가 108곳이다
 * (2026-09-03 실측). 문자열로만 비교하면 그 장소들에서 같은 사진이 두 번 나온다.
 *
 *   http://tong.visitkorea.or.kr/cms/resource/15/1868115_image2_1.jpg
 *   https://tong.visitkorea.or.kr/cms/resource/15/1868115_image2_1.jpg
 */
function photoKey(url: string): string {
  return url.replace(/^https?:/, "");
}

/*
 * 작은 사진 줄이 차지하는 높이. h-14(56px) + pb-1(4px).
 *
 * 이 자리를 **항상 남긴다.** 사진이 두 장 이상인 장소가 38%뿐이라(8,060곳 중
 * 3,059곳, 2026-09-03 실측) 줄을 있을 때만 그리면 상세를 열 때마다 화면이 68px씩
 * 밀린다 — 사진이 늦게 도착하는 만큼 그 이동이 눈에 띈다. 한 장뿐인 곳(52%)에서는
 * 빈 자리가 남지만, 배경 없이 비워 두면 눈에 걸리지 않는다.
 */
const PHOTO_STRIP_HEIGHT = "h-[60px]";

/** 사진 영역의 껍데기. 로딩·갤러리·이미지 없음 세 경우가 같은 높이를 쓴다. */
function PhotoAreaShell({
  main,
  strip,
  reserveStrip = true,
}: {
  main: ReactNode;
  strip?: ReactNode;
  /*
   * 뒤에 사진이 올 수 있는 동안만 자리를 잡는다. 사진이 없는 것이 확정된 자리에서는
   * 60px이 끝까지 비어 있을 뿐이고, 그만큼 장소명과 정보가 아래로 밀린다.
   */
  reserveStrip?: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      {main}
      {/* 자리를 남긴다는 것이 이 요소의 존재 이유라, 테스트가 그것을 집을 수
          있게 표식을 둔다. */}
      {reserveStrip && (
        <div data-testid="photo-strip-slot" className={`${PHOTO_STRIP_HEIGHT} shrink-0`}>
          {strip}
        </div>
      )}
    </div>
  );
}

/**
 * 도착한 사진만 나타나게 하는 이미지.
 *
 * 목록은 배열로 한 번에 오지만 이미지 자체는 브라우저가 한 장씩 받아온다. 그동안
 * 빈 회색 칸으로 두면 다 같이 떠오르는 것처럼 보여서, 각자 도착한 순간에 켜지게
 * 한다. 실패해도 켠다 — 안 켜면 대체 텍스트조차 보이지 않는다.
 */
function FadeInImage({
  src,
  alt,
  className,
  lazy = false,
  placeholderSrc,
}: {
  src: string;
  alt: string;
  className: string;
  lazy?: boolean;
  /**
   * 이미 화면에 떠 있던 작은 사진(카드 썸네일). 상세 조회로 받은 원본이 뜨기
   * 전까지 흐리게 깔아 둔다.
   *
   * 카드 목록은 작은 썸네일을, 상세는 원본 크기를 우선하도록 서로 다르게
   * 골라 쓴다(카드: recommendation_cards.py, 상세: hybrid_place_details.py) —
   * 같은 사진이라도 화질·크롭이 달라 그대로 바꿔치우면 사라졌다 나타나는
   * 것처럼 번쩍인다. 흐린 채로 계속 보여주면 "흐리다가 선명해진다"로 읽혀
   * 자연스럽다(블러업 패턴).
   */
  placeholderSrc?: string;
}) {
  const [isLoaded, setIsLoaded] = useState(false);

  const image = (
    <img
      src={src}
      alt={alt}
      loading={lazy ? "lazy" : undefined}
      /* 캐시에 이미 있으면 onLoad가 오지 않는다 — 그 경우 여기서 바로 켠다. */
      ref={(node) => {
        if (node?.complete) setIsLoaded(true);
      }}
      onLoad={() => setIsLoaded(true)}
      onError={() => setIsLoaded(true)}
      className={`${className} transition-opacity duration-300 ${
        isLoaded ? "opacity-100" : "opacity-0"
      } ${placeholderSrc ? "absolute inset-0" : ""}`}
    />
  );

  if (!placeholderSrc) return image;

  return (
    // overflow-hidden: 흐림 처리로 커진(scale-105) 미리보기가 둥근 모서리 밖으로
    // 삐져나오지 않게 자른다.
    <div className="relative overflow-hidden">
      <img
        src={placeholderSrc}
        alt=""
        aria-hidden
        data-testid="photo-blur-placeholder"
        className={`${className} scale-105 blur-md`}
      />
      {image}
    </div>
  );
}

/**
 * 상세 모달의 사진 영역. 여러 장이면 갤러리로, 한 장이면 지금까지처럼 한 장만 그린다.
 *
 * 두 출처를 합쳐서 본다. photos는 place_image_embeddings에 적재된 detailImage2
 * 사진이고, thumbnail_url은 places 행의 대표 이미지다. 사진 목록이 있는 장소가
 * 전체의 30%뿐이라(2026-08-31 실측) 목록만 보고 그리면 나머지 장소에서 지금
 * 보이던 사진이 사라진다.
 */
function PlacePhotoGallery({
  card,
  title,
  item,
}: {
  card: InfoPlaceCard;
  title: string;
  item?: RecommendationItem;
}) {
  const photos = card.photos ?? [];
  /*
   * 대표 이미지를 목록 맨 앞에 세우고 중복만 걷어낸다.
   *
   * 예전에는 목록이 비었을 때만 대표 이미지를 썼다. "목록이 이미 그 장소의
   * 사진들이니 덧붙이면 두 번 나온다"는 이유였는데, 실측하면 절반만 맞다 —
   * 사진 목록이 있는 6,830곳 중 대표 이미지가 목록에도 있는 곳은 3,706곳(54%)이고
   * 나머지 44%는 목록에 없다(2026-09-03). 그 44%에서는 카드에서 보고 눌러 들어온
   * 사진이 상세에서 사라졌다.
   *
   * 맨 앞에 두는 이유는 카드에서 방금 본 사진이라서다 — 뒤에 붙이면 상세를 열 때
   * 화면이 다른 사진으로 갈아치워진 것처럼 보인다.
   */
  const seen = new Set<string>();
  const urls = [
    ...(card.thumbnail_url ? [card.thumbnail_url] : []),
    ...photos.map((photo) => photo.url),
  ].filter((url) => {
    const key = photoKey(url);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const [activeIndex, setActiveIndex] = useState(0);

  // 모달을 연 채로 다른 장소의 상세가 도착하면 선택을 처음으로 되돌린다. 안 되돌리면
  // 사진이 3장인 곳에서 3번째를 보다가 1장짜리 장소로 바뀌었을 때 빈 자리가 남는다.
  const firstUrl = urls[0];
  useEffect(() => {
    setActiveIndex(0);
  }, [firstUrl]);

  if (urls.length === 0) return null;

  const safeIndex = Math.min(activeIndex, urls.length - 1);
  const placeName = card.place_name ?? title;

  return (
    <PhotoAreaShell
      main={
        <div className="relative">
          <FadeInImage
            /* src가 바뀌면 새로 받아오므로 다시 켜지게 remount한다 — key가 없으면
               이전 사진의 "도착함" 상태가 그대로 남아 안 온 사진이 보인다. */
            key={urls[safeIndex]}
            src={urls[safeIndex]}
            alt={urls.length > 1 ? `${placeName} 사진 ${safeIndex + 1}번째` : `${placeName} 이미지`}
            className="aspect-[5/3] w-full rounded-2xl bg-chip object-cover"
            // 로딩 중 보여주던 카드 썸네일과 이어지는 자리는 첫 번째 사진뿐이다 —
            // 갤러리 안에서 사용자가 직접 다른 사진으로 넘긴 경우는 "교체됐다"는
            // 인상이 문제가 아니라 원래 그런 동작이라 흐림 전환을 넣지 않는다.
            placeholderSrc={safeIndex === 0 ? (item?.image_url ?? undefined) : undefined}
          />
          {urls.length > 1 && (
            <span className="absolute bottom-2 right-2 rounded-full bg-black/60 px-2 py-0.5 text-xs font-medium text-white">
              {safeIndex + 1} / {urls.length}
            </span>
          )}
        </div>
      }
      strip={
        urls.length > 1 ? (
          <div
            className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1"
            role="group"
            aria-label={`${placeName} 사진 목록`}
          >
            {urls.map((url, index) => (
              <button
                key={`${url}-${index}`}
                type="button"
                onClick={() => setActiveIndex(index)}
                aria-label={`${placeName} 사진 ${index + 1}번째 보기`}
                aria-current={index === safeIndex}
                className={`h-14 w-14 shrink-0 overflow-hidden rounded-lg border-2 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                  index === safeIndex
                    ? "border-blue-600 dark:border-blue-400"
                    : "border-transparent opacity-70 hover:opacity-100"
                }`}
              >
                <FadeInImage
                  src={url}
                  alt=""
                  lazy
                  className="h-full w-full bg-gray-100 object-cover dark:bg-gray-800"
                />
              </button>
            ))}
          </div>
        ) : undefined
      }
    />
  );
}

/** 추천/INFO 어디서 열어도 같은 모양으로 PlaceDetails를 보여주는 상세 모달이다. */
export function RecommendationDetailPreviewModal({
  item,
  card,
  placeId: placeIdProp,
  placeName: placeNameProp,
  onClose,
}: RecommendationDetailPreviewModalProps) {
  const { device_location, language } = useTripState();
  const isEn = language === "en";
  const [detailCard, setDetailCard] = useState<InfoPlaceCard | null>(card ?? null);
  const [detailStatus, setDetailStatus] = useState<"loading" | "no_data" | "unavailable">(
    "loading",
  );
  // 호출부 4곳 모두 {selected && <모달/>}로 조건부 렌더링한다 — AnimatePresence로
  // 언마운트를 감지할 부모가 없다. 닫힐 때는 여기서 슬라이드다운을 먼저 재생하고,
  // 애니메이션이 끝난 뒤에야 실제 onClose(부모의 상태 제거)를 부른다.
  const [isClosing, setIsClosing] = useState(false);
  const handleClose = () => setIsClosing(true);
  const placeId = card?.place_id ?? item?.place_id ?? placeIdProp;
  const placeName = card?.place_name ?? item?.name ?? placeNameProp;
  const title =
    detailCard?.place_name ??
    card?.place_name ??
    item?.name ??
    placeNameProp ??
    (isEn ? "Place details" : "장소 상세 정보");
  const isLoading = detailStatus === "loading" && !detailCard;
  /*
   * 사진이 아예 없을 것을 **열 때 이미 안다.**
   *
   * 카드 이미지가 없는 장소 844곳 중 843곳(99.9%)은 상세 사진도 0장이다(2026-09-05
   * 실측, places ↔ place_image_embeddings 대조). 그래서 응답을 기다리지 않고 사진
   * 영역을 통째로 비우면, 응답이 와도 레이아웃이 바뀌지 않는다 — 장소명부터 바로
   * 시작해 첫 화면에 정보가 들어온다.
   *
   * 응답 후에 정하면 그 844곳이 전부 밀린다(10.5%). 이 방식에서 밀리는 것은 카드
   * 이미지가 없는데 상세 사진은 있는 예외 1곳뿐이다(8,067분의 1).
   *
   * **미리 알 수 있을 때만 적용한다.** 사진 유사 검색·지난 추천은 이름과 place_id만
   * 넘기고 열어서(호출부 참고) 판단 근거가 없다 — 그때는 종전대로 자리를 잡아 둔다.
   * 사진이 1장인지 2장 이상인지는 어느 경로에서도 미리 알 수 없으므로, 작은 사진
   * 줄의 자리 예약(PHOTO_STRIP_HEIGHT)은 그대로 둔다.
   */
  const knownImageUrl = item?.image_url ?? card?.thumbnail_url ?? null;
  const expectsNoPhoto = (item != null || card != null) && knownImageUrl == null;
  const showSkeleton = useDelayedSkeleton(isLoading);
  // 목적지 좌표와 현재 위치가 모두 있어야 길찾기 딥링크를 만들 수 있다.
  const canRoute =
    detailCard?.latitude != null && detailCard?.longitude != null && Boolean(device_location);
  /*
   * 상세를 기다리는 동안에도 버튼 자리를 잡아 둔다. 이 버튼은 스크롤 영역 바깥의
   * 하단 고정 바라, 늦게 생기면 그만큼 본문 높이가 줄며 읽던 자리가 밀린다.
   *
   * 자리만 잡고 누르지는 못하게 한다 — 목적지 좌표가 상세 응답에 실려 오므로
   * 그 전에는 열 지도가 없다. 추천 카드에는 좌표가 없어서(RecommendationItem에
   * 필드 자체가 없다) 미리 채울 수도 없다.
   *
   * 현재 위치가 없으면 자리도 잡지 않는다. 그 경우 상세가 와도 버튼은 끝내
   * 나오지 않으므로, 자리를 잡으면 영영 못 누르는 버튼을 보여주게 된다.
   */
  const showRouteFooter = Boolean(device_location) && (canRoute || isLoading);
  // 주소는 제목 바로 아래 전용 줄로 뺐으니 "관련 정보"에서는 뺀다(중복 제거).
  const addressText = detailCard?.answer_fields.address;
  // "관련 정보"(answer_fields)에서 개요는 아래 "개요" 섹션과 내용이 같아 제외한다(중복 제거).
  // 홈페이지는 answer_fields가 아니라 카드 최상위 필드다(질문 유형이 general_info가
  // 아니어도 백엔드가 채울 수 있다) — 하단 링크를 없앤 대신 여기서 합성해 넣는다.
  const answerEntries =
    detailCard && !isRealtimeParkingCard(detailCard) && !isRealtimeSubwayCard(detailCard)
      ? [
          ...Object.entries(detailCard.answer_fields).filter(
            ([key]) => key !== "overview" && key !== "address",
          ),
          ...(detailCard.homepage && !("homepage" in detailCard.answer_fields)
            ? ([["homepage", detailCard.homepage]] as [string, string][])
            : []),
        ]
      : [];
  const hasRealtimeDetails =
    (detailCard?.realtime_detail_items?.length ?? 0) > 0 || Boolean(detailCard?.realtime_map_url);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsClosing(true);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    const shouldEnrichCard = needsDetailEnrichment(card);
    if (card && !shouldEnrichCard) {
      setDetailCard(card);
      return;
    }
    // 이름만 있으면 상세를 조회한다. 혼잡도·행사 카드는 place_id가 없지만
    // 이름으로 조회해 전체 상세(좌표 포함)를 받는다.
    if (!placeName) {
      setDetailStatus("no_data");
      return;
    }
    let cancelled = false;
    // INFO 답변의 요약(주소·혼잡도·행사)은 상세 조회 중에도 남겨 둔다.
    setDetailCard(card ?? null);
    setDetailStatus("loading");

    void fetchRecommendationPlaceDetails({ place_id: placeId, place_name: placeName })
      .then((response) => {
        if (cancelled) return;
        if (response.status === "success" && response.place_card) {
          setDetailCard(
            card
              ? {
                  ...response.place_card,
                  question_type: card.question_type,
                  answer_fields: card.answer_fields,
                }
              : response.place_card,
          );
          return;
        }
        setDetailStatus(response.status === "unavailable" ? "unavailable" : "no_data");
      })
      .catch(() => {
        if (!cancelled) setDetailStatus("unavailable");
      });

    return () => {
      cancelled = true;
    };
  }, [card, placeId, placeName]);

  // .tb-shell의 contain:layout에 기대는 대신 document.body로 포탈해, 채팅
  // 스크롤 위치나 조상 요소의 overflow/포지셔닝과 무관하게 지금 보고 있는
  // 화면(진짜 뷰포트) 하단에 항상 붙는다(D-102: 채팅이 길어지면 시트가 화면
  // 기준이 아니라 문서 어딘가에 떨어져 붙는 것처럼 보이던 문제).
  return createPortal(
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-end" role="presentation">
      <motion.button
        type="button"
        aria-label={isEn ? "Close" : "닫기"}
        onClick={handleClose}
        className="absolute inset-0 bg-ink-strong/35"
        initial={{ opacity: 0 }}
        animate={{ opacity: isClosing ? 0 : 1 }}
        transition={{ duration: 0.22 }}
      />
      {/*
       * 높이를 **고정한다**(max-h가 아니라 h). 시트가 내용 높이로 정해지면 상세
       * 응답이 도착할 때 화면이 위로 자란다 — 개요·관련 정보·실시간 항목은 응답
       * 전에 자리를 잡을 수 없고(길이를 모른다), 정보 표만 스켈레톤으로 잡혀 있다.
       *
       * 전에는 사진 영역(약 283px)이 로딩 시점에 이미 상한을 채워서 그 성장이
       * 스크롤로 흡수됐다. 사진 없는 장소에서 영역을 접자 그게 드러났을 뿐,
       * 원래 있던 움직임이다 — 화면이 큰 기기에서는 사진이 있어도 자란다.
       *
       * 정보가 적은 장소는 아래가 비지만, 읽는 도중 시트가 밀려 올라오는 것보다
       * 낫다. 지도 앱들의 장소 시트가 같은 선택을 한다.
       */}
      <motion.section
        role="dialog"
        aria-modal="true"
        aria-labelledby="recommendation-detail-title"
        data-testid="place-detail-sheet"
        className="relative flex h-[88vh] w-full max-w-[640px] flex-col overflow-hidden rounded-t-3xl bg-bg shadow-card"
        initial={{ y: "100%" }}
        animate={{ y: isClosing ? "100%" : 0 }}
        transition={{ type: "spring", damping: 32, stiffness: 320 }}
        onAnimationComplete={() => {
          if (isClosing) onClose();
        }}
      >
        <span className="mx-auto mt-2.5 h-1.5 w-10 shrink-0 rounded-full bg-border" />

        <div className="flex shrink-0 justify-end px-4 pb-3 pt-5">
          <button
            type="button"
            onClick={handleClose}
            className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-ink shadow-resting transition-colors hover:bg-chip focus:outline-none focus:ring-2 focus:ring-brand"
            aria-label={isEn ? "Close details" : "상세 창 닫기"}
          >
            <X size={20} />
          </button>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 pb-5">
          {/* 사진이 있을 수 있는 장소는 세 경우(로딩·갤러리·이미지 없음) 모두
              PhotoAreaShell을 써서 같은 높이를 차지한다 — 로딩에서 갤러리로 바뀔 때
              화면이 밀리지 않게 하려면 자리가 같아야 한다. expectsNoPhoto인 장소는
              애초에 그 전환이 없으므로 자리를 잡지 않는다. */}
          {detailCard && (detailCard.photos?.length || detailCard.thumbnail_url) ? (
            /* 예외 1곳(8,067분의 1)은 카드에 이미지가 없는데 상세에 사진이 있다.
               그 장소에서는 사진이 도착한 시점에 갤러리가 생기며 아래가 밀린다 —
               사진을 안 보여주는 것보다 낫다. */
            <PlacePhotoGallery card={detailCard} title={title} item={item} />
          ) : expectsNoPhoto && detailStatus !== "unavailable" ? null : isLoading ? (
            <PhotoAreaShell
              main={
                /*
                 * item.image_url은 추천 카드를 만들 때 D가 이미 채워 보낸 대표
                 * 이미지다(QuickInfoPreview의 operating_hours_display와 같은
                 * 이유) — 상세 조회 응답을 기다리지 않고 카드에서 본 그 사진을
                 * 바로 보여준다. 응답이 오면 detailCard 기준 갤러리로 바뀐다.
                 */
                item?.image_url ? (
                  <FadeInImage
                    key={item.image_url}
                    src={item.image_url}
                    alt={`${title} 이미지`}
                    className="aspect-[5/3] w-full rounded-2xl bg-chip object-cover"
                  />
                ) : (
                  <div className="flex aspect-[5/3] animate-pulse items-center justify-center rounded-2xl bg-chip text-sm text-muted">
                    {isEn ? "Loading details..." : "상세 정보를 불러오는 중..."}
                  </div>
                )
              }
              strip={
                /*
                 * 사진이 여럿인 장소의 중앙값이 5장이라(실측) 다섯 칸을 잡아 둔다.
                 *
                 * 첫 칸에는 회전하는 아이콘을 얹는다. 큰 사진과 운영시간을 카드에서
                 * 이미 아는 값으로 먼저 채우고 나니(item.image_url·
                 * operating_hours_display), 정작 상세 조회가 아직 진행 중이라는
                 * 사실을 알려줄 곳이 이 자리 말고 남지 않았다 — bg-chip 펄스만으로는
                 * "로딩 중"인지 "빈 자리"인지 구분되지 않는다.
                 */
                <div className="-mx-1 flex gap-2 px-1 pb-1" aria-hidden>
                  <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-chip">
                    <Loader2
                      size={18}
                      data-testid="photo-strip-loading-spinner"
                      className="animate-spin text-muted"
                    />
                  </div>
                  {[1, 2, 3, 4].map((slot) => (
                    <div
                      key={slot}
                      className="h-14 w-14 shrink-0 animate-pulse rounded-lg bg-chip"
                    />
                  ))}
                </div>
              }
            />
          ) : !hasRealtimeDetails ? (
            <PhotoAreaShell
              // 여기서 끝이라 뒤에 올 사진이 없다. 실패 안내에는 줄 자리를 잡지 않는다.
              reserveStrip={!expectsNoPhoto}
              main={
                <div className="flex aspect-[5/3] items-center justify-center rounded-2xl border border-dashed border-border bg-chip text-sm text-muted">
                  {isEn
                    ? detailStatus === "unavailable"
                      ? "Couldn't load details."
                      : "No image available."
                    : detailStatus === "unavailable"
                      ? "상세 정보를 불러오지 못했어요."
                      : "등록된 이미지가 없어요."}
                </div>
              }
            />
          ) : null}

          <div className="flex flex-col gap-1.5">
            {item?.category && (
              <span className="w-fit rounded-full bg-chip px-2.5 py-1 text-xs font-bold text-brand">
                {item.category}
              </span>
            )}
            <h2 id="recommendation-detail-title" className="text-xl font-bold text-ink">
              {title}
            </h2>
            {item && (
              <div className="flex items-center gap-1.5 text-sm text-muted">
                <MapPin size={13} />
                <span>{travelShortLabel(item)}</span>
              </div>
            )}
            {addressText && <p className="text-xs text-muted">{addressText}</p>}
          </div>

          {isLoading ? (
            /* 운영시간을 이미 알면 그 줄은 실제 값이므로 스켈레톤을 한 줄 적게 둔다.
               줄 수는 지연과 무관하게 처음부터 최종값이다 — 지연에 묶으면 200ms
               지점에 표가 커지며 아래가 밀린다(showBars 주석 참고). */
            <InfoTableSkeleton
              rows={INFO_TABLE_SKELETON_ROWS - (item?.operating_hours_display ? 1 : 0)}
              showBars={showSkeleton}
              isEn={isEn}
              leadingRow={<QuickInfoPreview item={item} isEn={isEn} />}
            />
          ) : (
            detailCard && (
              <>
                <InfoTable card={detailCard} item={item} isEn={isEn} />
                <AccessibilityTable card={detailCard} isEn={isEn} />
              </>
            )
          )}

          {item?.recommendation_reason && (
            <section className="flex flex-col gap-1.5 rounded-2xl bg-sky-light p-4">
              <div className="flex items-center gap-1.5">
                <Sparkles size={14} className="text-brand-deep" />
                <p className="text-xs font-bold text-brand-deep">
                  {isEn ? "Why AI recommends this" : "AI가 추천하는 이유"}
                </p>
              </div>
              <p className="text-sm leading-relaxed text-ink">{item.recommendation_reason}</p>
            </section>
          )}

          {detailCard?.overview && (
            <section className="flex flex-col gap-1.5">
              <h3 className="text-xs font-bold text-label">{isEn ? "Overview" : "개요"}</h3>
              <p className="whitespace-pre-line text-sm leading-relaxed text-ink">
                {detailCard.overview}
              </p>
            </section>
          )}

          {!isLoading &&
            (detailCard ? (
              <>
                {answerEntries.length > 0 && (
                  <section className="rounded-xl bg-sky-light p-3">
                    <h3 className="text-sm font-semibold text-ink">
                      {isEn ? "Related info" : "관련 정보"}
                    </h3>
                    <dl className="mt-2 space-y-2 text-sm">
                      {answerEntries.map(([key, value]) => (
                        <div key={key} className="flex gap-2">
                          <dt className="shrink-0 text-muted">
                            {isEn
                              ? (ANSWER_FIELD_LABELS_EN[key] ?? ANSWER_FIELD_LABELS[key] ?? key)
                              : (ANSWER_FIELD_LABELS[key] ?? key)}
                          </dt>
                          <AnswerValue value={value} />
                        </div>
                      ))}
                    </dl>
                  </section>
                )}
                <RealtimeDetailEntries card={detailCard} />
                {((detailCard.population_forecasts?.length ?? 0) > 0 ||
                  (detailCard.concentration_forecasts?.length ?? 0) > 0 ||
                  detailCard.question_type === "realtime_traffic") && (
                  <section className="overflow-hidden rounded-xl border border-border bg-white">
                    <ConcentrationForecastBars card={detailCard} />
                    <PopulationForecastBars card={detailCard} />
                    <RoadTrafficStatusSection card={detailCard} />
                  </section>
                )}
                <PreferenceInsightsSection card={detailCard} />
              </>
            ) : (
              <p className="rounded-xl border border-dashed border-border p-4 text-sm text-muted">
                {isEn
                  ? detailStatus === "unavailable"
                    ? "Couldn't load details. Please try again shortly."
                    : "Details for this place aren't available yet."
                  : detailStatus === "unavailable"
                    ? "상세 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."
                    : "이 장소의 상세 정보는 아직 제공되지 않아요."}
              </p>
            ))}
        </div>

        {showRouteFooter && (
          <div className="shrink-0 bg-bg px-4 pb-7 pt-4">
            <button
              type="button"
              disabled={!canRoute}
              onClick={() => {
                if (!canRoute || !detailCard) return;
                openNaverDirections({
                  deviceLocation: device_location as string,
                  destLat: detailCard.latitude as number,
                  destLng: detailCard.longitude as number,
                  destName: detailCard.place_name ?? title,
                });
              }}
              className={`flex h-[52px] w-full items-center justify-center gap-2 rounded-full text-base font-bold transition-colors ${
                canRoute
                  ? "bg-brand text-white hover:bg-brand-deep"
                  : "cursor-not-allowed bg-chip text-muted"
              }`}
            >
              <Navigation size={18} />
              {isEn ? "Get directions on Naver Maps" : "네이버 지도로 길찾기"}
            </button>
          </div>
        )}
      </motion.section>
    </div>,
    document.body,
  );
}
