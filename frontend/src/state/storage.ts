/*
 * 역할: TripContext 상태를 sessionStorage에 저장하고 복원한다.
 * 입력: TripState 객체 또는 브라우저 sessionStorage에 남아 있는 JSON 문자열.
 * 출력: 저장 성공 여부 없이 side effect, 복원된 TripState 또는 null.
 * 호출 시점: TripProvider 초기화, 상태 변경, RESET 처리 시 호출된다.
 * TODO: 상태 버전이 바뀌면 migration 경로와 만료 정책을 추가한다.
 */

import type { TripState } from "./TripContext";
import type { ChatMessage, ChatPhase } from "../types";

const STORAGE_KEY = "tripbranch_state";
// 5: 개발자용 발화별 감사 기록(auditTurns)을 함께 저장.
const STORAGE_VERSION = 5;

interface StoredState {
  version: number;
  state: TripState;
}

function isTripState(value: unknown): value is TripState {
  if (!value || typeof value !== "object") return false;
  const state = value as Record<string, unknown>;
  return (
    typeof state.user_input === "string" &&
    Array.isArray(state.recommendations) &&
    Array.isArray(state.unverified_recommendations) &&
    Array.isArray(state.shown_place_ids) &&
    Array.isArray(state.messages) &&
    Array.isArray(state.auditTurns) &&
    state.messages.every(isChatMessage) &&
    isChatPhase(state.phase) &&
    (state.device_location === null || typeof state.device_location === "string") &&
    (state.error === null || typeof state.error === "string")
  );
}

function isChatPhase(value: unknown): value is ChatPhase {
  return (
    value === "idle" ||
    value === "interpreting" ||
    value === "waiting_for_debug_confirmation" ||
    value === "recommending" ||
    value === "ready" ||
    value === "error"
  );
}

function isChatMessage(value: unknown): value is ChatMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as Record<string, unknown>;
  if (typeof message.id !== "string" || typeof message.type !== "string") return false;
  if (message.type === "user_text" || message.type === "assistant_text") {
    return typeof message.text === "string";
  }
  if (message.type === "interpretation_summary") {
    return typeof message.text === "string";
  }
  if (message.type === "condition_debug") {
    return (
      typeof message.userInput === "string" &&
      typeof message.conditions === "object" &&
      (message.status === "pending" || message.status === "confirmed")
    );
  }
  /* 로컬 테스트용 "/status" 결과. 복원돼도 화면 표시 외의 영향은 없다. */
  if (message.type === "session_status") {
    return (
      (message.status === null || typeof message.status === "object") &&
      (message.error === null || typeof message.error === "string")
    );
  }
  if (message.type === "recommendation_result") {
    return (
      Array.isArray(message.recommendations) &&
      Array.isArray(message.unverified_recommendations) &&
      typeof message.elapsed_ms === "number" &&
      typeof message.server_elapsed_ms === "number"
    );
  }
  /* SCHEDULE-10 후속: 이 케이스가 없으면 schedule_result 메시지가 하나라도 있는
     세션은 isTripState()가 messages.every(isChatMessage)에서 걸려 세션 전체가
     복원 실패로 버려진다(place_info_result도 마찬가지였다) — 새로고침하면 SCHEDULE/INFO
     질문을 한 번이라도 한 대화가 통째로 사라지던 버그. */
  if (message.type === "schedule_result") {
    const schedule = message.schedule as Record<string, unknown> | null | undefined;
    return (
      typeof message.elapsed_ms === "number" &&
      !!schedule &&
      typeof schedule === "object" &&
      Array.isArray(schedule.items) &&
      typeof schedule.total_duration_min === "number" &&
      typeof schedule.route_summary === "string" &&
      typeof schedule.basis_note === "string" &&
      typeof schedule.elapsed_ms === "number"
    );
  }
  if (message.type === "place_info_result") {
    const card = message.card as Record<string, unknown> | null | undefined;
    return (
      !!card &&
      typeof card === "object" &&
      typeof card.question_type === "string" &&
      typeof card.answer_fields === "object" &&
      card.answer_fields !== null
    );
  }
  return false;
}

export function loadState(): TripState | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredState>;
    if (parsed.version !== STORAGE_VERSION || !isTripState(parsed.state)) return null;
    return parsed.state;
  } catch {
    return null;
  }
}

export function saveState(state: TripState): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ version: STORAGE_VERSION, state }));
  } catch {
    // sessionStorage can be unavailable; the app still works for the current tab.
  }
}

export function clearState(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
