/*
 * 역할: 위치 설정 화면에서 고른 검색 위치를 sessionStorage에 저장·복원한다.
 * 입력: 장소 이름 문자열.
 * 출력: 저장된 이름 또는 없으면 null.
 * 호출 시점: LocationPage가 고르거나 해제할 때, HomePage·ChatPage가 발화를 보낼 때.
 *
 * **TripState(state/storage.ts)에 두지 않는다.** 그쪽은 "새 대화"를 누르면
 * RESET으로 통째로 비워지는데, 검색 위치는 대화가 아니라 설정이라 새 대화에도
 * 남아야 한다. 취향이 preferenceStorage로 빠져 있는 것과 같은 이유다.
 *
 * **localStorage가 아니라 sessionStorage에 둔다.** 취향("조용한 곳을 좋아함")은
 * 며칠 뒤에도 유효하지만 검색 위치는 그날 그 자리의 값이다. 탭을 닫으면 함께
 * 사라지는 편이 "어제 맞춰둔 위치로 오늘도 찾아주는" 상황보다 낫다.
 *
 * 신원이 바뀌면 지운다 — state/localUserData.ts가 로그아웃에서 이 키를 함께 비운다.
 */

const SEARCH_CENTER_KEY = "tb_search_center";

export function loadSearchCenter(): string | null {
  try {
    const raw = sessionStorage.getItem(SEARCH_CENTER_KEY);
    if (raw === null) return null;
    const trimmed = raw.trim();
    return trimmed || null;
  } catch {
    /* sessionStorage가 막혀 있어도(시크릿 모드 등) 화면은 계속 동작해야 한다. */
    return null;
  }
}

export function saveSearchCenter(name: string | null): void {
  try {
    const trimmed = name?.trim();
    if (!trimmed) {
      sessionStorage.removeItem(SEARCH_CENTER_KEY);
      return;
    }
    sessionStorage.setItem(SEARCH_CENTER_KEY, trimmed);
  } catch {
    /* 위와 같다 — 저장하지 못해도 이번 화면 동작은 그대로 이어간다. */
  }
}

export { SEARCH_CENTER_KEY };
