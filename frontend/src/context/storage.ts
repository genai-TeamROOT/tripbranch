// TripState를 sessionStorage에 저장/복구/삭제하는 순수 함수 모음(storage 접근을 이 파일로 격리).
// 저장 포맷에 version 필드를 포함해, 이후 상태 구조가 바뀌어도 구버전 데이터를 안전하게
// 무시(초기화)할 수 있게 했다. 사용법: TripState 필드를 추가/변경했다면 STORAGE_VERSION을
// 올리고 isValidState()의 검증 로직도 같이 갱신할 것.

import type { TripState } from "./tripReducer";

const STORAGE_KEY = "tripbranch_state";
const STORAGE_VERSION = 1;

interface StoredEnvelope {
  version: number;
  state: TripState;
}

function isValidState(value: unknown): value is TripState {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.user_input === "string" &&
    Array.isArray(candidate.recommendation_results) &&
    Array.isArray(candidate.unverified_recommendations) &&
    Array.isArray(candidate.shown_place_ids)
  );
}

export function loadState(): TripState | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const parsed = JSON.parse(raw) as Partial<StoredEnvelope>;
    if (parsed.version !== STORAGE_VERSION || !isValidState(parsed.state)) {
      return null;
    }
    return parsed.state;
  } catch {
    return null;
  }
}

export function saveState(state: TripState): void {
  try {
    const envelope: StoredEnvelope = { version: STORAGE_VERSION, state };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(envelope));
  } catch {
    // sessionStorage may be unavailable (e.g. private browsing) -- state
    // simply won't survive a refresh in that case.
  }
}

export function clearState(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
