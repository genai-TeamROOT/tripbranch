/*
 * 역할: 장소 사진 한 장을 카드 썸네일 자리에 그리고, 사진이 없거나 못 불러오면
 *       같은 모양의 자리표시를 보여준다.
 * 입력: 이미지 주소(등록되지 않은 장소는 null/undefined로 온다).
 * 출력: <img> 또는 "사진 없음" 자리표시.
 * 호출 시점: 추천 카드(PlaceCard), 행사 카드(PlaceInfoCard의 RealtimeEventCard),
 *            사진 유사 검색 결과(PhotoSimilarResultMessage)가 썸네일을 그릴 때.
 *
 * 세 화면이 같은 블록을 복사해 쓰면서 자리표시가 서로 달랐다(카테고리 영문 슬러그 /
 * "행사" / 빈 칩). 사진이 없다는 사실은 어느 화면에서든 같은 뜻이므로 한 모양으로 묶는다.
 */

import { useState } from "react";
import { ImageOff } from "lucide-react";

interface PlaceThumbnailProps {
  /** 없으면 자리표시를 그린다. */
  src?: string | null;
}

export function PlaceThumbnail({ src }: PlaceThumbnailProps) {
  /*
   * 실패한 주소를 그대로 담는다. boolean으로 두면 같은 카드가 다른 사진으로 다시
   * 그려질 때(재랭킹 등) 실패 표시가 남아 멀쩡한 사진까지 가린다 — 목록은
   * key={place_id}로 그려지므로 src만 바뀌고 이 컴포넌트는 그대로 살아 있다.
   *
   * 이전에는 onError에서 event.currentTarget.style.visibility를 직접 바꿨는데,
   * React가 모르는 변경이라 같은 <img> DOM이 재사용될 때 숨김이 그대로 남았다.
   */
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  if (!src || failedSrc === src) {
    return (
      // 사진이 없는 것과 원본이 사라진 것을 구분해 보여주지 않는다 — 사용자가 할 수
      // 있는 일이 같고, 목록에서 자리표시가 연달아 나올 때 설명이 길면 장소 이름보다
      // 눈에 띈다.
      <span
        data-testid="place-thumbnail-placeholder"
        className="flex h-28 w-full items-center justify-center rounded-2xl bg-chip text-gray-400"
      >
        <ImageOff size={26} strokeWidth={1.5} aria-hidden />
      </span>
    );
  }

  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      className="h-28 w-full rounded-2xl object-cover transition-transform duration-300 group-hover:scale-105"
      onError={() => setFailedSrc(src)}
    />
  );
}
