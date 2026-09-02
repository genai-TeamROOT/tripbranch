/*
 * 역할: 사이드바의 즐겨찾기·채팅 히스토리를 localStorage에 저장·복원한다.
 * 입력: 화면에서 만든 FavoritePlace/ChatHistoryEntry 배열.
 * 출력: 저장된 값 또는 없으면 빈 배열.
 * 호출 시점: SideDrawerContent가 마운트/변경 시 호출한다.
 * TODO: 백엔드에 즐겨찾기/채팅 히스토리 저장 엔드포인트가 생기면 이 모듈을 API
 *   호출로 교체한다 — 지금은 세션 기기에만 남는 목업이다(DESIGN_SYSTEM.md §10.6).
 */

const FAVORITES_KEY = "tb_favorites";
const CHAT_HISTORY_KEY = "tb_chat_history";

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

export function loadChatHistory(): ChatHistoryEntry[] {
  return readJsonArray<ChatHistoryEntry>(CHAT_HISTORY_KEY);
}

export function saveChatHistory(history: ChatHistoryEntry[]): void {
  writeJsonArray(CHAT_HISTORY_KEY, history);
}
