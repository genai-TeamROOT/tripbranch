/*
 * 역할: 계정에 저장한 일정 목록을 한 번만 받아 사이드바 두 벌이 나눠 쓴다.
 * 입력: GET /api/schedules.
 * 출력: 사이드바가 그리는 SavedScheduleEntry 배열.
 * 호출 시점: SideDrawerContent가 마운트될 때, 일정을 저장·삭제한 뒤.
 *
 * **chatSessions.ts와 같은 구조다.** 데스크톱 사이드바와 모바일 드로어는 CSS로
 * 하나만 보이게 하는 것이지 둘 다 마운트된다 — 캐시가 없으면 화면을 열 때마다
 * 같은 목록을 두 번 받아온다.
 *
 * 로컬 거울을 두지 않는 이유도 같다. 저장한 일정은 서버에 있고 소유자도 서버가
 * 안다 — 목록만 로컬에 복사해두면 지운 일정이 되살아나는 쪽이 더 나쁘다.
 */

import { fetchSavedSchedules } from "../api/trip";
import type { SavedScheduleSummary } from "../types";

export interface SavedScheduleEntry {
  id: string;
  label: string;
  /* 저장한 날. **last_active_at이 아니라 created_at을 쓴다** — 저장한 일정은
     그 뒤로 바뀌지 않으므로 "언제 저장했는지"가 사용자가 찾는 단서다. */
  date: string;
}

function toEntry(schedule: SavedScheduleSummary): SavedScheduleEntry {
  const at = new Date(schedule.created_at);
  return {
    id: schedule.id,
    label: schedule.title,
    date: Number.isNaN(at.getTime())
      ? ""
      : at.toLocaleDateString("ko-KR", { month: "long", day: "numeric" }),
  };
}

let cached: Promise<SavedScheduleEntry[]> | null = null;

async function load(): Promise<SavedScheduleEntry[]> {
  const response = await fetchSavedSchedules();
  return response.items.map(toEntry);
}

/**
 * 저장한 일정 목록. 페이지 로드당 한 번만 실제로 요청한다.
 *
 * 실패는 던지지 않고 빈 목록으로 돌려준다 — 토큰이 없거나(401) 서버에 못 닿아도
 * 사이드바의 나머지 기능은 계속 써야 한다(loadChatSessions와 같은 판단).
 */
export function loadSavedSchedules(): Promise<SavedScheduleEntry[]> {
  cached ??= load().catch(() => []);
  return cached;
}

let inflight: Promise<SavedScheduleEntry[]> | null = null;

type Listener = (entries: SavedScheduleEntry[]) => void;
const listeners = new Set<Listener>();

/**
 * 목록이 갱신되면 알려준다. 사이드바가 구독한다.
 *
 * **대화 목록과 방식이 다른 이유.** 저쪽은 새 대화가 생기는 계기가 TripContext의
 * 상태 변화(턴 완료)라 사이드바가 그걸 보면 됐다. 저장은 일정 카드의 버튼
 * 클릭이고 그 컴포넌트는 사이드바와 멀리 떨어져 있어, 상태를 타고 전달하려면
 * 전역 상태에 저장 전용 필드를 하나 더 만들어야 한다. 목록 캐시가 이미 이
 * 모듈에 있으니 여기서 알리는 편이 작다.
 *
 * 반환값은 구독 해제 함수다.
 */
export function subscribeSavedSchedules(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * 서버에서 다시 받아온다. 일정을 저장했거나 지웠을 때 쓴다.
 *
 * 받아온 뒤 구독자에게 알린다 — 저장하고 사이드바를 봤는데 없으면 사용자는
 * 저장이 안 된 줄 안다(실제로 새로고침해야 보였다).
 */
export function refreshSavedSchedules(): Promise<SavedScheduleEntry[]> {
  if (inflight) return inflight;
  const request = load()
    .catch(() => [] as SavedScheduleEntry[])
    .then((entries) => {
      inflight = null;
      listeners.forEach((listener) => listener(entries));
      return entries;
    });
  inflight = request;
  cached = request;
  return request;
}

/** 테스트가 페이지 로드 경계를 흉내 낼 수 있게 캐시를 비운다. */
export function resetSavedSchedulesCache(): void {
  cached = null;
  inflight = null;
  listeners.clear();
}
