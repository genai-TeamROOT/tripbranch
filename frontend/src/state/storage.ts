import type { TripState } from "./TripContext";

const STORAGE_KEY = "tripbranch_state";
const STORAGE_VERSION = 1;

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
    Array.isArray(state.shown_place_ids)
  );
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
