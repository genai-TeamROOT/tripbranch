/*
 * 역할: 올린 사진과 분위기가 닮은 장소를 대화에 보여준다.
 * 입력: 올린 사진 축소본, 진행 상태, 검색 중심 이름, 장소 목록, 후보 수.
 * 출력: 사진(우측 말풍선) + 결과(좌측 말풍선). 카드를 누르면 상세가 열린다.
 * 호출 시점: ChatMessageList가 photo_similar_result 메시지를 만났을 때.
 *
 * **사진은 사용자 쪽, 결과는 응답 쪽에 둔다.** 대화의 나머지와 같은 규칙이다 —
 * 사용자 발화는 `ml-auto`, 응답은 `mr-auto`. 사진은 사용자가 올린 것이므로
 * 오른쪽이 맞다.
 *
 * **결과는 가로로 늘어놓는다.** 세로 목록이면 카드 하나가 한 줄을 통째로 쓰면서
 * 오른쪽이 비고, 5곳이면 화면이 그만큼 길어진다. 가로로 두면 사진이 나란히
 * 놓여 분위기를 한눈에 견줄 수 있다 — 이 화면의 목적이 그 비교다.
 *
 * **유사도를 백분율로 보여주지 않는다.** 그 값은 순위를 위한 것이지 "얼마나
 * 닮았다"의 눈금이 아니다(D-094). 정말 닮았는지는 사용자가 상세를 열어 본다.
 */

import { useState } from "react";
import type { PhotoSimilarPlace } from "../../types";
import { RecommendationDetailPreviewModal } from "./RecommendationDetailPreviewModal";
import { PlaceThumbnail } from "../PlaceThumbnail";

/** 이 미만이면 벡터가 사진 한 장에 좌우된다(D-087). 표시를 달리한다. */
const RELIABLE_PHOTO_COUNT = 2;

interface PhotoSimilarResultMessageProps {
  imageUrl?: string | null;
  status?: "loading" | "done";
  centerName: string;
  places: PhotoSimilarPlace[];
  candidateCount: number;
}

export function PhotoSimilarResultMessage({
  imageUrl,
  status = "done",
  centerName,
  places,
  candidateCount,
}: PhotoSimilarResultMessageProps) {
  const [selected, setSelected] = useState<PhotoSimilarPlace | null>(null);

  return (
    <>
      {imageUrl && (
        <img src={imageUrl} alt="올린 사진" className="ml-auto max-h-48 rounded-md object-cover" />
      )}

      <div className="mr-auto max-w-full text-sm text-ink">
        {status === "loading" ? (
          <p className="flex items-center gap-2 text-muted">
            <Spinner />
            분위기가 닮은 곳을 찾고 있어요…
          </p>
        ) : places.length === 0 ? (
          /*
           * 두 상황을 구분한다. 문구가 하나면 "왜 안 나왔는지"를 사용자도
           * 개발자도 알 수 없다.
           *
           *   후보 0곳    지금 갈 수 있는 곳 자체가 없었다(영업시간·반경).
           *   후보 있음   후보는 있는데 사진 벡터가 없다. 적재가 안 된 구다.
           */
          <p>
            {candidateCount === 0 ? (
              <>
                <span className="font-medium">{centerName}</span> 주변에서 지금 갈 수 있는 곳을 찾지
                못했어요. 다른 지역으로 찾아볼까요?
              </>
            ) : (
              <>
                <span className="font-medium">{centerName}</span> 주변 {candidateCount}곳을 봤는데
                사진과 비교할 수 있는 곳이 없었어요. 아직 사진을 모으지 못한 지역이에요.
              </>
            )}
          </p>
        ) : (
          <>
            <p className="mb-3">
              <span className="font-medium">{centerName}</span> 주변에서 분위기가 닮은 곳이에요.
              눌러서 사진을 확인해 보세요.
            </p>
            {/* 좁은 화면에서는 가로 스크롤로 흘린다. 줄바꿈하면 다시 세로로 길어진다. */}
            <ul className="scrollbar-none -mx-1 flex gap-3 overflow-x-auto px-1 pb-1">
              {places.map((place, index) => (
                <li key={place.content_id} className="w-28 shrink-0">
                  <button
                    type="button"
                    onClick={() => setSelected(place)}
                    className="group text-left"
                  >
                    {/*
                     * 비교에 실제로 쓴 사진이다(place_image_embeddings의 첫 장).
                     * places.first_image_url이 아니다 — 절반 이상이 다른 주소라
                     * 대표 이미지를 쓰면 비교하지 않은 사진을 보여주게 된다.
                     */}
                    <PlaceThumbnail src={place.image_url} />
                    <span className="mt-2 flex items-baseline gap-1">
                      <span className="text-[11px] tabular-nums text-brand">{index + 1}</span>
                      <span className="line-clamp-2 text-xs font-bold text-ink">{place.title}</span>
                    </span>
                    {place.photo_count < RELIABLE_PHOTO_COUNT && (
                      /* 사진 한 장으로 만든 벡터라 덜 믿을 만하다는 것을 숨기지 않는다. */
                      <span className="text-[11px] leading-tight text-muted">사진 1장 비교</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {selected && (
        <RecommendationDetailPreviewModal
          placeId={selected.content_id}
          placeName={selected.title}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}

function Spinner() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="size-4 animate-spin text-muted"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
