/*
 * 역할: 위치 설정 화면에서 정한 출발지와 검색 기준을 sessionStorage에 담는다.
 * 입력: 고른 장소 이름(각각), 또는 비우기.
 * 출력: 지금 정해져 있는 두 값.
 * 호출 시점: LocationPage가 정할 때, HomePage·ChatPage가 발화를 보내거나 상단
 *   위치 pill을 그릴 때.
 *
 * **두 값은 다른 질문의 답이다.**
 *
 *   출발지(origin)      "사용자가 어디 있는가" — 이동시간을 재는 시작점
 *   검색 기준(center)   "어디 주변을 찾을까" — 후보를 모으는 중심
 *
 * D-067이 둘을 분리한 이유가 여기 있다. "지금 혜화역인데 안국역 근처"를 하나로
 * 합치면 거리·경로가 전부 안국역에서 계산돼, 자동차 1분으로 표시된 곳이 실제로는
 * 23분이었다. 그래서 화면도 고른 장소를 둘 중 무엇으로 쓸지 묻는다.
 *
 * 각각 백엔드의 AgentRequest.selected_current_location·selected_search_center로
 * 간다. 비어 있으면 예전 동작 그대로다 — 출발지는 기기 좌표, 검색 기준은 발화가 정한다.
 *
 * **대화가 아니라 설정이라 TripState에 두지 않는다.** 거기 두면 "새 대화"를 누를 때
 * RESET으로 지워진다 — 실제로 위치를 골라도 사이드바 홈을 거치면 무시되는 문제가
 * 있었다. 취향이 preferenceStorage로 빠져 있는 것과 같은 이유다.
 *
 * **localStorage가 아니라 sessionStorage에 둔다.** 취향("조용한 곳을 좋아함")은
 * 며칠 뒤에도 유효하지만 이 값들은 그날 그 자리의 값이다.
 *
 * 신원이 바뀌면 지운다 — state/localUserData.ts가 로그아웃에서 함께 비운다.
 */

const LOCATION_SETTINGS_KEY = "tb_location_settings";

export interface LocationSettings {
  /** 출발지로 쓸 장소 이름. null이면 기기 좌표를 그대로 쓴다. */
  origin: string | null;
  /** 검색 기준으로 쓸 장소 이름. null이면 발화나 기기 좌표가 정한다. */
  center: string | null;
}

const EMPTY: LocationSettings = { origin: null, center: null };

function normalize(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function loadLocationSettings(): LocationSettings {
  try {
    const raw = sessionStorage.getItem(LOCATION_SETTINGS_KEY);
    if (!raw) return EMPTY;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return EMPTY;
    const value = parsed as Record<string, unknown>;
    return { origin: normalize(value.origin), center: normalize(value.center) };
  } catch {
    /* 저장소가 막혀 있거나(시크릿 모드 등) 값이 깨졌어도 화면은 계속 동작해야 한다. */
    return EMPTY;
  }
}

/*
 * 값이 바뀌면 알려준다. 상단 위치 pill이 구독한다.
 *
 * 저장소는 값이 바뀌어도 React에 알려주지 않는다. 위치 설정 화면에서 정한 순간
 * 헤더가 그대로면 사용자는 반영이 안 된 줄 안다 — 시트로 열린 화면 뒤에서 홈이
 * 계속 마운트된 채라 다시 그려지지 않기 때문이다(savedSchedules와 같은 방식).
 */
type Listener = (settings: LocationSettings) => void;
const listeners = new Set<Listener>();

export function subscribeLocationSettings(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function write(next: LocationSettings): LocationSettings {
  try {
    if (next.origin === null && next.center === null) {
      sessionStorage.removeItem(LOCATION_SETTINGS_KEY);
    } else {
      sessionStorage.setItem(LOCATION_SETTINGS_KEY, JSON.stringify(next));
    }
  } catch {
    /* 저장하지 못해도 이번 화면 동작은 그대로 이어간다. */
  }
  listeners.forEach((listener) => listener(next));
  return next;
}

/** 출발지를 정한다. null이면 기기 좌표로 되돌린다. */
export function setLocationOrigin(origin: string | null): LocationSettings {
  return write({ ...loadLocationSettings(), origin: normalize(origin) });
}

/** 검색 기준을 정한다. null이면 발화·기기 좌표가 정하도록 되돌린다. */
export function setLocationCenter(center: string | null): LocationSettings {
  return write({ ...loadLocationSettings(), center: normalize(center) });
}

export function clearLocationSettings(): void {
  write(EMPTY);
}

export { LOCATION_SETTINGS_KEY };
