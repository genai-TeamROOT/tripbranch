/*
 * 역할: 사이드바의 즐겨찾기를 localStorage에 저장·복원한다.
 * 입력: 화면에서 만든 FavoritePlace 배열.
 * 출력: 저장된 값 또는 없으면 빈 배열.
 * 호출 시점: SideDrawerContent가 마운트/변경 시 호출한다.
 *
 * **채팅 히스토리는 여기서 빠졌다**(TP-222 후속). 계정에서 받아오므로
 * state/chatSessions.ts가 맡는다. ChatHistoryEntry 타입만 남겨 둔 것은 화면이
 * 쓰는 모양이 그대로이기 때문이다 — 서버 응답을 이 모양으로 바꿔 넣는다.
 *
 * TODO: 즐겨찾기도 계정으로 옮긴다. 채팅 화면(SavedPlacesBar)은 이미
 *   /state/{session_id}/saved-places를 쓰는데 사이드바만 아직 이 기기에 남는다 —
 *   같은 개념이 두 곳에 따로 있는 상태다(DESIGN_SYSTEM.md §10.6).
 */

const FAVORITES_KEY = "tb_favorites";

export interface FavoritePlace {
  id: string;
  label: string;
}

export interface ChatHistoryEntry {
  id: string;
  label: string;
  date: string;
  placeName: string | null;
}

export function createId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

function readJsonArray<T>(key: string): T[] {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function writeJsonArray<T>(key: string, value: T[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* localStorage가 막혀 있어도(시크릿 모드 등) 화면 동작 자체는 계속돼야 한다. */
  }
}

export function loadFavorites(): FavoritePlace[] {
  return readJsonArray<FavoritePlace>(FAVORITES_KEY);
}

export function saveFavorites(favorites: FavoritePlace[]): void {
  writeJsonArray(FAVORITES_KEY, favorites);
}

