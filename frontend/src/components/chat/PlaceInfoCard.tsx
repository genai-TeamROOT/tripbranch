/*
 * 역할: INFO 장소 질의의 간략 답변과 전체 장소 상세 정보를 한 카드에 표시한다.
 * 입력: C가 한 번의 상세 조회로 내려준 InfoPlaceCard.
 * 출력: 질문 답 요약과 클릭 시 열리는 장소 상세 모달.
 * 호출 시점: ChatMessageList가 place_info_result 메시지를 렌더할 때 호출된다.
 */

import { useState } from "react";
import type { InfoPlaceCard as InfoPlaceCardData, RealtimeInfoDetailItem } from "../../types";
import { useTripState } from "../../state/TripContext";
import {
  groupSubwayArrivals,
  parseSubwayArrival,
  subwayLineColor,
  type SubwayLineGroup,
} from "../../utils/subwayDisplay";
import { PlaceCardRow } from "./PlaceCardRow";
import {
  ConcentrationForecastBars,
  PopulationForecastBars,
  RoadTrafficStatusSection,
} from "./CongestionForecastBars";
import { RecommendationDetailPreviewModal } from "./RecommendationDetailPreviewModal";

const FIELD_LABELS: Record<string, string> = {
  operating_hours: "운영시간",
  rest_date: "휴무일",
  fee: "요금",
  parking: "주차",
  parking_fee: "주차 요금",
  baby_carriage: "유모차",
  pet: "반려동물 동반",
  credit_card: "카드 결제",
  restroom: "화장실",
  address: "주소",
  telephone: "전화번호",
  /* 무장애 여행 정보(D-077). 계약 키를 그대로 두면 화면에 wheelchair_access처럼
   * 영문 키가 그대로 찍힌다. */
  wheelchair_access: "휠체어 접근",
  accessible_restroom: "장애인 화장실",
  accessible_parking: "장애인 주차",
  wheelchair_rental: "휠체어 대여",
  stroller_rental: "유모차 대여",
  nursing_room: "수유실",
  guide_dog: "보조견 동반",
  braille_block: "점자블록",
  braille_promotion: "점자 안내물",
  audio_guide: "음성 안내",
  public_transport: "대중교통",
  infant_family_etc: "영유아·가족 편의",
  disability_etc: "장애인 편의 기타",
  overview: "개요",
  homepage: "홈페이지",
  concentration: "혼잡도",
  event: "행사",
  "상권 지역": "상권 지역",
  "상권 기준": "상권 기준",
  업종: "업종",
  "실시간 활동": "실시간 활동",
  "기준 시각": "기준 시각",
  안내: "안내",
};

/* 이 목록에 있는 필드는 백엔드 계약 키라 항상 같은 항목만 나온다. 그 외
   자유 텍스트 키(상권 지역 등)는 영어 화면에서도 한글 그대로 둔다. */
const FIELD_LABELS_EN: Record<string, string> = {
  operating_hours: "Hours",
  rest_date: "Closed on",
  fee: "Admission",
  parking: "Parking",
  parking_fee: "Parking fee",
  baby_carriage: "Stroller rental",
  pet: "Pets allowed",
  credit_card: "Card payment",
  restroom: "Restroom",
  address: "Address",
  telephone: "Phone",
  wheelchair_access: "Wheelchair access",
  accessible_restroom: "Accessible restroom",
  accessible_parking: "Accessible parking",
  wheelchair_rental: "Wheelchair rental",
  stroller_rental: "Stroller rental",
  nursing_room: "Nursing room",
  guide_dog: "Guide dogs allowed",
  braille_block: "Braille blocks",
  braille_promotion: "Braille guides",
  audio_guide: "Audio guide",
  public_transport: "Public transport",
  infant_family_etc: "Family amenities",
  disability_etc: "Other accessibility",
  overview: "Overview",
  homepage: "Website",
  concentration: "Crowd level",
  event: "Event",
};

interface PlaceInfoCardProps {
  card: InfoPlaceCardData;
}

interface OperatingHoursRow {
  period: string;
  hours: string;
}

function parseOperatingHours(value: string): OperatingHoursRow[] | null {
  // TourAPI는 "[기간]시간[기간]시간"처럼 구분자 없이 이어 붙여 내려준다.
  // 원문은 바꾸지 않고 카드에서만 기간별 행으로 나눈다.
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
    <div className="mt-2 grid gap-2 sm:grid-cols-2">
      {rows.map(({ period, hours }) => (
        <div key={period} className="rounded-xl bg-chip px-3 py-2">
          <p className="text-xs font-semibold text-label">{period}</p>
          <p className="mt-0.5 text-sm text-ink">{hours}</p>
        </div>
      ))}
    </div>
  );
}

function formatCardValue(fieldKey: keyof InfoPlaceCardData, value: string) {
  // TourAPI 원문의 예외 안내(※)는 문장에 붙여 두면 읽기 어렵다. 원문 뜻은
  // 바꾸지 않고 줄만 분리한다. 요금의 "-" 항목도 카드에서 불릿처럼 보이게 한다.
  let formatted = value.replace(/\s*※\s*/g, "\n※ ");
  if (fieldKey === "fee") {
    formatted = formatted.replace(/(?:^|\s)-\s*/g, "\n- ");
  }
  return formatted.trim();
}

function isRealtimeParkingCard(card: InfoPlaceCardData): boolean {
  return ["realtime_parking", "realtime_public_parking"].includes(card.question_type);
}

type ParkingLotType = "공영" | "민영" | "기타";

const PARKING_TYPE_BADGE_STYLE: Record<ParkingLotType, string> = {
  공영: "bg-sky-light text-brand-deep",
  민영: "bg-gold-tint text-[#8a5a12]",
  기타: "bg-chip text-muted",
};

// 서버는 이름 앞에 "[공영]"/"[민영]"을 붙여 보낸다(기타는 접두어 없음). 뱃지로
// 따로 떼어 보여주는 편이 대괄호 텍스트보다 한눈에 들어온다.
function splitParkingTitle(title: string): { type: ParkingLotType; name: string } {
  const matched = title.match(/^\[(공영|민영)\]\s*(.+)$/);
  if (!matched) return { type: "기타", name: title };
  return { type: matched[1] as ParkingLotType, name: matched[2] };
}

// _format_realtime_parking()이 만드는 "상태(거리, 총 대수, 요금)" 형태를 상태 칩과
// 메타 태그들로 나눈다. 괄호가 없으면(형식이 안 맞으면) 값 전체를 상태로 둔다.
function parseParkingValue(value: string): { status: string; available: boolean; meta: string[] } {
  const matched = value.match(/^(.+?)\(([^)]*)\)\s*$/);
  if (!matched) return { status: value, available: false, meta: [] };
  const status = matched[1].trim();
  // 백엔드가 ", "로 이어 붙인다(_format_realtime_parking). 콤마 하나로 나누면
  // "약 1,076m"처럼 숫자 자체에 천 단위 콤마가 있는 항목이 잘린다.
  const meta = matched[2]
    .split(", ")
    .map((part) => part.trim())
    .filter(Boolean);
  const available = /^현재\s+[\d,]+대\s+주차\s*(가능|중)/.test(status);
  return { status, available, meta };
}

// 근처 주차장 응답은 최대 9곳까지 나와, 이름 줄 + 값 줄로 다 펼치면 세로로 너무
// 길어진다. 뱃지·상태 칩으로 밀도를 낮추고, 거리·대수·요금은 아래 한 줄에
// 작은 태그로 모은다.
function RealtimeParkingSummary({ title, value }: { title: string; value: string }) {
  const { type, name } = splitParkingTitle(title);
  const { status, available, meta } = parseParkingValue(value);
  return (
    <article className="min-w-0 rounded-xl border border-border bg-white px-3 py-2.5">
      <div className="flex min-w-0 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <span
            className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${PARKING_TYPE_BADGE_STYLE[type]}`}
          >
            {type}
          </span>
          <span className="min-w-0 truncate text-sm font-bold text-ink" title={name}>
            {name}
          </span>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${
            available ? "bg-emerald-50 text-emerald-700" : "bg-chip text-muted"
          }`}
        >
          {status}
        </span>
      </div>
      {meta.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-x-2.5 gap-y-1 pl-[calc(1.75rem+0.375rem)] text-xs text-muted">
          {meta.map((part) => (
            <span key={part}>{part}</span>
          ))}
        </div>
      )}
    </article>
  );
}

// 목록형 실시간 카드(주차·행사)가 공유하는 "더 보기" 자리. 접힌 채로 시작해
// 답변 흐름을 밀어내지 않다가, 누르면 나머지를 펼친다.
function MoreItemsButton({
  hiddenCount,
  unit,
  onClick,
}: {
  hiddenCount: number;
  unit: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="flex items-center justify-center gap-1 rounded-lg py-1.5 text-xs font-semibold text-brand-deep hover:bg-chip"
      onClick={onClick}
    >
      {hiddenCount}{unit} 더 보기
      <span aria-hidden="true">⌄</span>
    </button>
  );
}

// 기본으로 보여줄 주차장 수. 근처 주차장(최대 9곳)·공영주차장(최대 5곳) 응답이
// 전부 펼쳐지면 카드가 답변 흐름을 밀어내므로, 나머지는 펼쳐야 보이게 접는다.
const REALTIME_PARKING_COLLAPSED_COUNT = 3;

function RealtimeParkingList({ answers }: { answers: [string, string][] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? answers : answers.slice(0, REALTIME_PARKING_COLLAPSED_COUNT);
  const hiddenCount = answers.length - visible.length;
  return (
    <section className="grid gap-2 px-4 py-3">
      {visible.map(([title, value]) => (
        <RealtimeParkingSummary key={title} title={title} value={value} />
      ))}
      {hiddenCount > 0 && (
        <MoreItemsButton hiddenCount={hiddenCount} unit="곳" onClick={() => setExpanded(true)} />
      )}
    </section>
  );
}

// event(TourAPI 행사)도 realtime_event(서울시 실시간 행사)와 같은 가로 스크롤
// 사진 카드로 보여준다 — 둘 다 realtime_detail_items 모양(제목/부제/썸네일)으로
// 내려오므로 렌더는 공유하고 판정만 question_type을 더 받는다.
function isEventCardRow(card: InfoPlaceCardData): boolean {
  return card.question_type === "realtime_event" || card.question_type === "event";
}

// 추천 카드(PlaceCard)와 같은 너비·비율의 사진 카드다 — 폭이 다르면 같은 줄에
// 섞였을 때(추천 결과 다음에 행사가 오는 경우 등) 스크롤 리듬이 어긋난다.
function RealtimeEventCard({ item }: { item: RealtimeInfoDetailItem }) {
  const openable = Boolean(item.external_url);
  return (
    <li className="w-40 shrink-0">
      <div
        className={`relative w-full text-left${openable ? " cursor-pointer" : ""}`}
        role={openable ? "link" : undefined}
        tabIndex={openable ? 0 : undefined}
        aria-label={openable ? `${item.title} 행사 정보 보기` : undefined}
        onClick={
          openable
            ? () => window.open(item.external_url as string, "_blank", "noopener")
            : undefined
        }
        onKeyDown={
          openable
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  window.open(item.external_url as string, "_blank", "noopener");
                }
              }
            : undefined
        }
      >
        <div className="group relative overflow-hidden rounded-2xl">
          {item.thumbnail_url ? (
            <img
              src={item.thumbnail_url}
              alt=""
              loading="lazy"
              className="h-28 w-full rounded-2xl object-cover transition-transform duration-300 group-hover:scale-105"
              onError={(event) => {
                event.currentTarget.style.visibility = "hidden";
              }}
            />
          ) : (
            <span className="flex h-28 w-full items-center justify-center rounded-2xl bg-chip text-xs text-muted">
              행사
            </span>
          )}
        </div>
        <div className="pt-2">
          <p className="line-clamp-2 text-sm font-bold text-ink">{item.title}</p>
          {item.subtitle && (
            <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted">
              {item.subtitle}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

// 행사는 이름 자체가 길어 주차장처럼 3곳으로 접으면 답변보다 목록이 먼저
// 눈에 띈다. 대신 가로 스크롤이라 접을 필요가 없다 — 추천 결과와 같은 방식
// (PlaceCardRow)으로 한 줄에 늘어놓고 옆으로 넘겨 보게 한다.
function RealtimeEventCardRow({ items }: { items: RealtimeInfoDetailItem[] }) {
  return (
    <div className="px-4 py-3">
      <PlaceCardRow>
        {items.map((item) => (
          <RealtimeEventCard key={item.title} item={item} />
        ))}
      </PlaceCardRow>
    </div>
  );
}

function isRealtimeSubwayCard(card: InfoPlaceCardData): boolean {
  return card.question_type === "realtime_subway";
}

// 한 방면(상행/하행 등) 안의 도착 한 건. 행선지(종착역)와 도착 안내를
// 한 줄에 놓는다 — 방면 묶음 헤더가 이미 방향을 말해주므로 여기서는
// 반복하지 않는다.
function SubwayArrivalRow({ item }: { item: RealtimeInfoDetailItem }) {
  const { arrival } = parseSubwayArrival(item.subtitle ?? "");
  const arrivalKnown = arrival !== null && !arrival.includes("미제공");
  const destination = item.details["종착역"] ? `${item.details["종착역"]}행` : "행선지 정보 미제공";
  return (
    <div className="flex min-w-0 items-center justify-between gap-2">
      <span className="min-w-0 truncate text-xs text-ink">{destination}</span>
      {arrival && (
        <span
          className={`shrink-0 rounded-full px-1.5 py-0.5 text-[11px] font-semibold ${
            arrivalKnown ? "bg-emerald-50 text-emerald-700" : "bg-white text-muted"
          }`}
        >
          {arrival}
        </span>
      )}
    </div>
  );
}

// 같은 역·같은 호선이라도 상행/하행은 다른 방향이라, 방면마다 별도 칸으로
// 나눠 나란히 보여준다(2026-09-02 실사용 지적) — 나열 순서만으로는 구분이
// 안 됐다.
function SubwayLineGroupCard({ group }: { group: SubwayLineGroup }) {
  return (
    <article className="min-w-0 rounded-xl border border-border bg-white px-3 py-2.5">
      <div className="flex min-w-0 items-center gap-1.5">
        <span
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: subwayLineColor(group.stationLine) }}
          aria-hidden="true"
        />
        <span className="min-w-0 truncate text-sm font-bold text-ink" title={group.stationLine}>
          {group.stationLine}
        </span>
      </div>
      <div
        className={`mt-2 grid gap-2 ${group.directions.length > 1 ? "grid-cols-2" : "grid-cols-1"}`}
      >
        {group.directions.map((direction) => (
          <div key={direction.direction} className="min-w-0 rounded-lg bg-chip px-2 py-1.5">
            <p className="text-[11px] font-semibold text-muted">{direction.direction}</p>
            <div className="mt-1 grid gap-1">
              {direction.items.map((item, index) => (
                <SubwayArrivalRow key={`${item.title}-${index}`} item={item} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}

function SubwayArrivalList({ items }: { items: RealtimeInfoDetailItem[] }) {
  const groups = groupSubwayArrivals(items);
  return (
    <section className="grid gap-2 px-4 py-3">
      {groups.map((group) => (
        <SubwayLineGroupCard key={group.stationLine} group={group} />
      ))}
    </section>
  );
}

export function PlaceInfoCard({ card }: PlaceInfoCardProps) {
  const [showDetail, setShowDetail] = useState(false);
  const isEn = useTripState().language === "en";
  const answers = Object.entries(card.answer_fields);

  return (
    <article className="mr-auto w-full overflow-hidden rounded-2xl bg-white shadow-resting">
      {card.thumbnail_url && (
        // 기본 카드에서 장소를 바로 알아볼 수 있도록, 작은 아이콘보다 충분히 큰
        // 중간 높이 썸네일을 카드 상단에 둔다. 상세 영역에서는 중복하지 않는다.
        <div className="flex h-44 w-full items-center justify-center overflow-hidden bg-chip">
          <img
            src={card.thumbnail_url}
            alt={isEn ? `${card.place_name ?? "Place"} image` : `${card.place_name ?? "장소"} 이미지`}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        </div>
      )}
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        aria-haspopup="dialog"
        aria-label={
          isEn ? `View details for ${card.place_name ?? "place"}` : `${card.place_name ?? "장소"} 상세 보기`
        }
        onClick={() => setShowDetail(true)}
      >
        <span className="min-w-0 text-sm font-bold text-ink">
          {card.place_name ?? (isEn ? "Place details" : "장소 상세 정보")}
        </span>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-sky-light px-3 py-1 text-xs font-semibold text-brand-deep">
          {isEn ? "View details" : "상세 보기"}
          <span aria-hidden="true">↗</span>
        </span>
      </button>

      {isRealtimeParkingCard(card) && answers.length > 0 ? (
        <RealtimeParkingList answers={answers} />
      ) : isEventCardRow(card) && (card.realtime_detail_items?.length ?? 0) > 0 ? (
        <RealtimeEventCardRow items={card.realtime_detail_items ?? []} />
      ) : isRealtimeSubwayCard(card) && (card.realtime_detail_items?.length ?? 0) > 0 ? (
        <SubwayArrivalList items={card.realtime_detail_items ?? []} />
      ) : answers.length > 0 ? (
        <dl className="px-4 py-3 text-sm">
          {answers.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className="shrink-0 text-muted">
                {isEn ? (FIELD_LABELS_EN[key] ?? FIELD_LABELS[key] ?? key) : (FIELD_LABELS[key] ?? key)}
              </dt>
              <dd className="min-w-0 flex-1 whitespace-pre-line text-ink">
                {key === "operating_hours" && parseOperatingHours(value) ? (
                  <OperatingHoursRows rows={parseOperatingHours(value) ?? []} />
                ) : (
                  formatCardValue(key as keyof InfoPlaceCardData, value)
                )}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      <ConcentrationForecastBars card={card} />
      <PopulationForecastBars card={card} />
      <RoadTrafficStatusSection card={card} />

      {showDetail && (
        <RecommendationDetailPreviewModal card={card} onClose={() => setShowDetail(false)} />
      )}
    </article>
  );
}
