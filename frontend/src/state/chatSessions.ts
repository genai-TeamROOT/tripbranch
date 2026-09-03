/*
 * 역할: 계정의 대화 목록을 한 번만 받아 사이드바 두 벌이 나눠 쓴다.
 * 입력: GET /api/sessions.
 * 출력: 사이드바가 그리는 ChatHistoryEntry 배열.
 * 호출 시점: SideDrawerContent가 마운트될 때, 이름 바꾸기·삭제가 실패했을 때.
 *
 * **캐시가 테스트 편의가 아니라 실제 요구다.** 데스크톱 사이드바와 모바일 드로어는
 * CSS로 하나만 보이게 하는 것이지 둘 다 마운트된다 — 캐시가 없으면 화면을 열
 * 때마다 같은 목록을 두 번 받아온다.
 *
 * 로컬 거울을 두지 않는다. 취향(preferenceSync)은 게스트가 가입할 때 넘겨줄 값이
 * 있어 localStorage를 남겼지만, 대화는 이미 서버에 있고 소유자도 서버가 안다 —
 * 목록만 로컬에 복사해두면 지운 대화가 되살아나는 쪽이 더 나쁘다.
 */

import { fetchChatSessions } from "../api/trip";
import type { ChatSessionSummary } from "../types";
import type { ChatHistoryEntry } from "./sidebarStorage";

/*
 * 서버 요약을 화면이 쓰는 모양으로 바꾼다.
 *
 * 날짜에서 연도를 뺀다 — 목록 한 줄에 제목·날짜·장소가 함께 들어가야 해서 자리가
 * 좁고, 대부분은 최근 대화다.
 */
export function toHistoryEntry(session: ChatSessionSummary): ChatHistoryEntry {
  const at = new Date(session.last_active_at);
  return {
    id: session.session_id,
    label: session.title,
    date: Number.isNaN(at.getTime())
      ? ""
      : at.toLocaleDateString("ko-KR", { month: "long", day: "numeric" }),
    location: session.location,
  };
}

let cached: Promise<ChatHistoryEntry[]> | null = null;

async function load(): Promise<ChatHistoryEntry[]> {
  const response = await fetchChatSessions();
  return response.sessions.map(toHistoryEntry);
}

/**
 * 대화 목록. 페이지 로드당 한 번만 실제로 요청한다.
 *
 * 실패는 던지지 않고 빈 목록으로 돌려준다 — 토큰이 없거나(401) 서버에 못 닿아도
 * 사이드바의 나머지 기능은 계속 써야 한다. 화면에는 "아직 대화 기록이 없어요"가
 * 뜬다.
 */
export function loadChatSessions(): Promise<ChatHistoryEntry[]> {
  cached ??= load().catch(() => []);
  return cached;
}

let inflight: Promise<ChatHistoryEntry[]> | null = null;

/**
 * 서버에서 다시 받아온다. 이름 바꾸기·삭제가 실패해 화면과 서버가 갈렸을 때,
 * 그리고 새 대화가 생겨 목록에 넣어야 할 때 쓴다.
 *
 * **진행 중인 요청이 있으면 그것을 함께 쓴다.** 사이드바는 데스크톱과 모바일
 * 드로어 두 벌이 동시에 마운트돼 있어(CSS로 하나만 보일 뿐이다) 같은 계기에
 * 둘 다 이 함수를 부른다 — 막지 않으면 같은 목록을 두 번 받아온다.
 */
export function refreshChatSessions(): Promise<ChatHistoryEntry[]> {
  if (inflight) return inflight;
  const request = load()
    .catch(() => [] as ChatHistoryEntry[])
    .then((entries) => {
      inflight = null;
      return entries;
    });
  inflight = request;
  cached = request;
  return request;
}

/** 테스트가 페이지 로드 경계를 흉내 낼 수 있게 캐시를 비운다. */
export function resetChatSessionsCache(): void {
  cached = null;
  inflight = null;
}
