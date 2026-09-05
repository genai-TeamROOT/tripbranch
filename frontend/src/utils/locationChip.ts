/*
 * 역할: 위치 설정값을 상단 위치 칩이 그릴 모양으로 바꾼다.
 * 입력: 지금 정해져 있는 출발지·검색 기준, 그리고 둘 다 없을 때 쓸 대체 이름.
 * 출력: 한 칸으로 그릴지 두 칸으로 그릴지, 각 칸에 넣을 (잘린) 이름, 화면 낭독용 문구.
 * 호출 시점: HomePage·ChatPage가 AppHeader에 넘길 값을 만들 때.
 *
 * **왜 두 칸이 필요한가.** 예전에는 `center ?? origin ?? …` 사다리로 하나만 골라
 * 보여줬는데, 그러면 검색 기준이 있을 때 출발지가 화면에서 사라진다. "지금
 * 안국역인데 광화문역 근처"라고 말하면 헤더는 광화문역만 말하지만 카드의 이동시간과
 * 거리는 전부 안국역에서 잰 값이다(D-067). 사용자는 그 기준점을 화면 어디서도 볼 수
 * 없었다. 위치 설정 화면은 지금도 둘을 갈라 보여주고 있어서 두 화면이 다른 사실을
 * 말하던 셈이다.
 *
 * **둘이 같으면 한 칸으로 접는다.** `안국역 → 안국역`은 같은 이름을 두 번 쓰는 것이라
 * 읽는 사람이 얻는 게 없다. 두 칸이 기본이라 사용자는 매 턴 "출발 → 검색" 구조를
 * 보게 되고, 그래서 한 칸으로 접혀 있어도 "같은 곳이구나"로 읽힌다.
 */

import type { LocationSettings } from "../state/locationSettings";

/** 출발지를 따로 정하지 않았을 때 그 자리에 쓰는 이름. */
export const DEVICE_LOCATION_LABEL = "현재 위치";

/*
 * 이름 하나가 차지할 수 있는 최대 글자수.
 *
 * 375px 화면에서 칩이 쓸 수 있는 폭은 295px이고(헤더 좌우 여백 32 + 햄버거와 간격
 * 48을 뺀 값), 그중 88px은 칩 내부 고정분(좌우 여백·아이콘 둘·화살표)이라 이름
 * 둘이 나눠 쓸 폭은 207px이다. 한글은 14px 글꼴에서 글자당 약 14px이므로 둘을
 * 합쳐 14~15자가 물리적 한계다.
 *
 * **그래서 이 상한은 좁은 화면을 위한 값이 아니다.** 그쪽은 CSS truncate가 받는다.
 * 이 값이 막는 것은 넓은 화면에서 긴 이름 하나가 칩을 통째로 잡아먹는 경우다 —
 * 장소 검색에는 실제로 `COSMOS BIGBANG 20TH ANNIVERSARY MEDIA EXHIBITION` 같은
 * 48자짜리가 걸린다.
 *
 * 10자는 사용자가 위치로 고르는 이름을 다 담는다 — 광화문역(4), 성수동(3),
 * 종로구(3), 현재 위치(5), 국립중앙박물관(7). 장소 스냅샷 16,860건(축제·전시까지
 * 섞여 위치로 고를 이름보다 긴 쪽)으로도 62%가 10자 이하다.
 */
export const MAX_CHIP_NAME_LENGTH = 10;

const ELLIPSIS = "…";

/*
 * 코드포인트로 센다. `.length`는 UTF-16 단위라 이모지가 섞인 이름을 반쪽만 잘라
 * 깨진 글자를 남긴다.
 */
export function truncateName(name: string, max: number = MAX_CHIP_NAME_LENGTH): string {
  const points = Array.from(name);
  if (points.length <= max) return name;
  return points.slice(0, max).join("") + ELLIPSIS;
}

export type LocationChipModel =
  | {
      kind: "single";
      /* 잘린 이름. 화면에 그대로 그린다. */
      name: string;
      /* 이 자리가 기기 좌표인가 — 깜빡이는 점을 붙일지 정한다. */
      isDeviceLocation: boolean;
      /* 낭독용 문구. 자르지 않은 원래 이름이 들어간다. */
      description: string;
    }
  | {
      kind: "pair";
      origin: string;
      center: string;
      isDeviceLocation: boolean;
      description: string;
    };

/*
 * 낭독 문구는 위치 설정 화면의 말투를 그대로 쓴다 — 두 화면이 같은 말을 해야
 * 사용자가 옮겨 다니며 다시 배우지 않는다.
 *
 * **자르지 않은 이름을 넣는다.** 화면에서 `…`로 잘린 이름이 낭독까지 잘리면 그
 * 사용자는 어디인지 알 방법이 없다.
 */
function describe(origin: string, center: string): string {
  return `${origin}에서 출발, ${center} 주변에서 검색`;
}

/**
 * 위치 칩이 그릴 모양을 정한다.
 *
 * @param settings 지금 정해져 있는 출발지·검색 기준.
 * @param fallbackCenter 둘 다 비어 있을 때 검색 기준 자리에 쓸 이름. 대화가 이미
 *   해석해 둔 위치가 있으면 그것을 넘긴다(없으면 기기 좌표를 쓴다는 뜻이라 null).
 */
export function buildLocationChipModel(
  settings: LocationSettings,
  fallbackCenter: string | null = null,
): LocationChipModel {
  const origin = settings.origin;
  /* 검색 기준을 비워두면 출발지가 검색 중심이 되고, 그것도 없으면 대화가 해석한
     위치가, 그것도 없으면 기기 좌표가 중심이 된다(agent_context/service.py). */
  const center = settings.center ?? settings.origin ?? fallbackCenter;

  const originLabel = origin ?? DEVICE_LOCATION_LABEL;
  const centerLabel = center ?? DEVICE_LOCATION_LABEL;
  const isDeviceLocation = origin === null;

  /* 둘이 같은 곳을 가리키면 한 칸으로 접는다. 출발지를 정하지 않았는데 검색
     기준도 없는 경우(둘 다 기기 좌표)도 여기로 온다. */
  if (originLabel === centerLabel) {
    return {
      kind: "single",
      name: truncateName(centerLabel),
      isDeviceLocation,
      description: describe(originLabel, centerLabel),
    };
  }

  return {
    kind: "pair",
    origin: truncateName(originLabel),
    center: truncateName(centerLabel),
    isDeviceLocation,
    description: describe(originLabel, centerLabel),
  };
}
