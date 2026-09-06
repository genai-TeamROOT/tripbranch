/*
 * 역할: 사이드바/드로어 안에 들어가는 내용. 내비게이션·언어·대화 기록·계정.
 * 입력: 현재 라우트, TripContext 언어/메시지 상태, 계정의 대화 목록.
 *
 * **즐겨찾기와 저장한 일정은 여기 없다**(2026-09-04). 각자 제 화면이 이미 있고
 * 그쪽이 더 많은 일을 한다 — 즐겨찾기는 위치 설정 화면(검색으로 추가·이름 바꾸기·
 * 출발지/검색기준 지정·10개 제한), 저장한 일정은 일정 화면
 * (`components/schedule/SavedScheduleList`). 사이드바 쪽은 목록과 삭제만 있는
 * 축소판이었고, 즐겨찾기는 "추가" 버튼이 어차피 위치 설정 화면으로 보냈다.
 * 출력: 라우트 이동, 언어 변경, 대화 목록 편집, 로그인 입구(게스트) 또는 계정 팝업.
 * 호출 시점: DesktopSidebar(768px 이상 상시 패널)와 모바일 드로어가 공유한다.
 *   컨테이너만 다르고 내용은 하나다 — 두 번 만들지 않는다(DESIGN_SYSTEM.md 6.17).
 * 근거: package_D/DESIGN_SYSTEM.md §6.17.
 */

import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Home, LogIn, LogOut, MapPin, MoreHorizontal, Route, Sparkles } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { identityDisplay, isGuestSession, type IdentityDisplay } from "../../auth/identityLabel";
import { detachChatRequest } from "../../state/chatAbortController";
import { sheetState } from "../../state/sheetNav";
import { useTripDispatch, useTripState } from "../../state/TripContext";
import type { Language } from "../../types";
import {
  deleteChatSession,
  renameChatSession,
  resumeChatSession,
} from "../../api/trip";
import { loadChatSessions, refreshChatSessions } from "../../state/chatSessions";
import { clearLocalUserData } from "../../state/localUserData";
import { type ChatHistoryEntry } from "../../state/sidebarStorage";

/*
 * 줄마다 메뉴가 붙는 목록은 대화 하나다. 예전에는 저장한 일정도 여기 있어서
 * `MenuTarget = { kind, id }`와 `isTarget()`으로 어느 목록인지 구분했는데, 일정
 * 목록이 일정 화면으로 옮겨가(`components/schedule/SavedScheduleList`) 구분할
 * 대상이 없어졌다 — 이제 열린 줄의 id 하나만 든다.
 */

interface SideDrawerContentProps {
  /** 모바일 드로어에서만 넘긴다 — 링크를 누르면 드로어를 닫기 위해서다. */
  onNavigate?: () => void;
}

const NAV_ITEM_CLASS =
  "flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm font-semibold transition-colors";

const ACCOUNT_MENU_ITEM_CLASS =
  "flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-medium transition-colors";

/*
 * 아바타 + 이름 + 부제. **계정 버튼과 팝업 헤더에 같은 모양이 두 번 들어간다** —
 * 따로 적어 두면 한쪽만 고쳐져 팝업을 열 때 이름이 달라 보인다.
 *
 * 아바타는 이름 첫 글자다. 프로필 사진을 받는 경로가 아예 없다(가입은 이름·이메일·
 * 비밀번호만 받고, 소셜 로그인도 없다) — 빈 회색 원을 두면 아직 안 불러온 것처럼
 * 보인다.
 *
 * 겉이 <button>인 자리에도 들어가므로 <div>가 아니라 <span>으로 짠다.
 */
function IdentityRow({ identity }: { identity: IdentityDisplay }) {
  return (
    <>
      <span
        aria-hidden
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-bold text-white"
      >
        {identity.initial}
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-semibold text-ink">{identity.name}</span>
        <span className="truncate text-[11px] text-muted">{identity.subtitle}</span>
      </span>
    </>
  );
}

/*
 * 지원 언어는 ko/en 두 개다. Figma 프로토타입은 中文·日本語까지 2×2로 그렸지만,
 * 언어를 늘리는 건 화면 작업이 아니라 앱 전체 문구 맵을 추가하는 콘텐츠 작업이라
 * 여기서 버튼만 만들면 눌러도 아무 일이 일어나지 않는다. 실제 지원하는 것만 그린다.
 */
const LANGUAGES: Array<{ code: Language; label: string }> = [
  { code: "ko", label: "한국어" },
  { code: "en", label: "English" },
];

export function SideDrawerContent({ onNavigate }: SideDrawerContentProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const dispatch = useTripDispatch();
  const state = useTripState();
  const isEn = state.language === "en";
  const { session, status, signOut } = useAuth();

  /*
   * 채팅 히스토리는 계정에서 온다(GET /api/sessions). 예전에는 localStorage
   * 목업이었는데 **항목을 넣는 코드가 아예 없어** 늘 비어 있었다.
   *
   * 로컬 거울을 두지 않는다 — 취향(preferenceSync)과 다른 점이다. 취향은 게스트가
   * 가입할 때 넘겨줘야 할 값이지만, 대화는 이미 서버에 있고 그 세션의 소유자도
   * 서버가 안다. 목록만 로컬에 복사해두면 지운 대화가 되살아나는 쪽이 더 나쁘다.
   */
  const [history, setHistory] = useState<ChatHistoryEntry[]>([]);
  /*
   * 메뉴와 이름 바꾸기는 **어느 목록의 어느 줄인지**를 함께 들고 있다.
   *
   * 예전에는 id 문자열만 들고 있었는데, 대화와 저장한 일정 두 목록이 그 하나를
   * 나눠 쓰면 한쪽 메뉴를 열 때 다른 쪽이 닫힌다 — 두 목록에 같은 id가 있으면
   * 양쪽이 동시에 열리기까지 한다(대화 id와 일정 id는 다른 체계라 실제로 겹칠
   * 일은 없지만, 겹치지 않는다는 것에 기대는 코드는 두지 않는다).
   *
   * 목록별로 상태를 두 벌 만들지 않은 이유는 **한 번에 하나만 열려야** 하기
   * 때문이다. 두 벌이면 대화 메뉴를 열어둔 채 일정 메뉴도 열려 메뉴 두 개가
   * 동시에 떠 있게 된다.
   */
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  /* 계정 관련 항목은 이 팝업 안에만 있다 — §6 주석 참고. */
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const renameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    void loadChatSessions().then((entries) => {
      if (active) setHistory(entries);
    });
    return () => {
      active = false;
    };
  }, [session?.user?.id]);
  /*
   * 새 대화가 생기면 목록에 바로 넣는다. 새로고침해야 나타나면 방금 한 대화가
   * 없는 것처럼 보인다.
   *
   * **턴이 끝난 뒤에 받아온다.** session_id는 스트리밍 도중에 먼저 도착하는데,
   * 목록에 들어가려면 제목이 있어야 하고(제목 없는 세션은 대화로 치지 않는다)
   * 제목은 백엔드가 턴을 저장할 때 붙는다 — 그전에 물으면 방금 만든 대화가
   * 목록에서 빠진 채로 온다.
   *
   * 세션 하나당 한 번만 받아온다. 매 턴 받아오면 날짜·장소가 함께 최신이 되지만,
   * 그건 목록에 이미 있는 줄의 겉모습일 뿐이라 요청을 더 낼 이유가 못 된다.
   */
  const listedSessionRef = useRef<string | null>(null);
  useEffect(() => {
    if (state.phase !== "ready" || !state.session_id) return;
    if (listedSessionRef.current === state.session_id) return;
    listedSessionRef.current = state.session_id;

    let active = true;
    void refreshChatSessions().then((entries) => {
      if (active) setHistory(entries);
    });
    return () => {
      active = false;
    };
  }, [state.phase, state.session_id]);

  useEffect(() => {
    if (renaming) renameInputRef.current?.focus();
  }, [renaming]);

  const hasConversation = state.messages.length > 0;
  const isGuest = status === "ready" && session ? isGuestSession(session) : false;
  const identity = session ? identityDisplay(session, state.language) : null;

  function go(path: string, options?: { sheet?: boolean }) {
    // 위치·일정은 새 페이지가 아니라 지금 화면 위에 바텀시트로 뜬다(§5) — 지금
    // location을 backgroundLocation으로 실어 보내야 닫았을 때 여기로 돌아온다.
    navigate(path, options?.sheet ? { state: sheetState(location) } : undefined);
    onNavigate?.();
  }

  /*
   * **"새 채팅"만 활성 판정이 다르다.** 대화가 남아 있으면 라우트가 "/"여도
   * 비활성으로 그린다. 라벨을 "홈"에서 바꾼 것은 동작이 그쪽이기 때문이다 —
   * 누르면 세션을 지우고(`RESET`) 첫 화면으로 간다.
   * 다시 누르면 세션을 지우는 파괴적 동작이라, "이미 여기 있음"으로 보이면 안 된다(6.17).
   */
  function goHome() {
    /* openConversation과 같은 이유다 — 홈으로 돌아가면 대화가 비워지는데,
       오던 답변이 그 빈 화면에 붙으면 안 된다. 여기서도 끊지 않는다. */
    detachChatRequest();
    dispatch({ type: "RESET" });
    navigate("/");
    onNavigate?.();
  }

  /*
   * **계정 사용자만 이 팝업을 본다**(§6). 게스트에게는 로그아웃 자리가 아예 없어서
   * 예전에 있던 "정말 나가시겠어요" 확인 단계도 함께 없앴다 — 게스트 로그아웃은
   * 되돌릴 수 없어 한 번 끊었던 것인데, 이제 그 버튼에 닿을 길이 없다.
   *
   * 계정 사용자에게는 확인을 붙이지 않는다. 다시 로그인하면 그대로 돌아오므로,
   * 되돌릴 수 있는 동작에까지 확인을 붙이면 확인이라는 신호 자체가 값싸진다.
   */
  function closeAccountMenu() {
    setAccountMenuOpen(false);
  }

  async function handleSignOut() {
    try {
      await signOut();
      /* 신원만 끊고 이 기기의 데이터를 두면 다음 신원의 화면에 앞사람의 대화·취향·
         즐겨찾기·검색 위치가 그대로 남는다. 함께 비운다(state/localUserData.ts). */
      clearLocalUserData();
      dispatch({ type: "RESET" });
      /* 이동은 따로 시키지 않는다 — 세션이 사라지면 RequireUser가 게스트 신원을
         새로 발급해 같은 자리에서 앱이 계속 열려 있다. */
    } finally {
      closeAccountMenu();
      onNavigate?.();
    }
  }

  /*
   * 지난 대화를 펼치고 **이어서 대화할 수 있게 되살린다.**
   *
   * 조회가 아니라 resume을 부른다. 세션 TTL이 30분이라 목록의 대화는 거의 전부
   * 만료돼 있고(실측: 106개 중 1개만 살아 있었다), 조회만 하면 이어 물었을 때
   * 새 세션이 생겨 목록에 줄이 하나 더 늘고 맥락도 끊긴다. resume은 대화를
   * 되살리되 낡은 조건(날씨·GPS·되묻기)은 버린다 — 사흘 전 "비 오는데"가 오늘의
   * 조건으로 남으면 안 되기 때문이다.
   */
  async function openConversation(sessionId: string) {
    try {
      const detail = await resumeChatSession(sessionId);
      /* 답변이 오는 중에 다른 대화를 열면 그 답변이 여기 붙는다. 화면을 바꾸기
         직전에 화면에서 떼어낸다 — **resume이 성공한 뒤다.** 먼저 떼면 열기가
         실패했을 때 화면은 그대로인데 오던 답변만 사라진다. 끊지는 않으므로
         서버는 답변을 끝내 저장하고, 나중에 그 대화를 열면 거기 있다. */
      detachChatRequest();
      dispatch({ type: "RESTORE_SESSION", payload: detail });
      go("/chat");
    } catch {
      /* 이미 지워졌거나 서버에 못 닿는 경우다. 목록을 다시 받아 화면과 서버를
         맞춘다 — 없는 대화가 목록에 남아 있으면 눌러도 계속 실패한다. */
      void refreshChatSessions().then(setHistory);
    }
  }

  function commitRename(id: string) {
    const trimmed = renameDraft.trim();
    if (trimmed) {
      /* 화면을 먼저 바꾸고 서버에 보낸다 — 이름 바꾸기는 되돌릴 수 있는 동작이라
         응답을 기다리는 동안 입력칸을 붙잡아 둘 이유가 없다. 실패하면 서버 값으로
         되돌린다 — 바뀐 척 남겨두면 다음에 열었을 때 예전 이름이 돌아와 있어 더
         혼란스럽다. 일정 목록도 같은 규칙을 쓴다(`SavedScheduleList`). */
      setHistory((prev) =>
        prev.map((item) => (item.id === id ? { ...item, label: trimmed } : item)),
      );
      void renameChatSession(id, trimmed).catch(() => {
        void refreshChatSessions().then(setHistory);
      });
    }
    setRenaming(null);
  }

  /* 빈 제목은 이름 바꾸기를 취소한 것으로 친다(commitRename의 `if (trimmed)`).
     서버도 빈 제목을 거부하므로 보내봐야 400이다. */

  const pathname = location.pathname;
  const navItems: Array<{
    key: string;
    label: string;
    icon: typeof Home;
    active: boolean;
    onClick: () => void;
  }> = [
    {
      key: "home",
      label: state.language === "en" ? "New chat" : "새 채팅",
      icon: Home,
      active: pathname === "/" && !hasConversation,
      onClick: goHome,
    },
    {
      key: "preferences",
      label: state.language === "en" ? "Preferences" : "취향 설정",
      icon: Sparkles,
      active: pathname === "/preferences",
      onClick: () => go("/preferences"),
    },
    {
      key: "location",
      label: state.language === "en" ? "Location" : "위치 설정",
      icon: MapPin,
      active: pathname === "/location",
      onClick: () => go("/location", { sheet: true }),
    },
    {
      key: "schedule",
      label: state.language === "en" ? "Schedule" : "일정",
      icon: Route,
      active: pathname === "/schedule",
      onClick: () => go("/schedule", { sheet: true }),
    },
  ];

  return (
    <div className="scrollbar-none flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 pb-5">
      {/* 1. 내비게이션 */}
      <nav
        aria-label={state.language === "en" ? "Main menu" : "주요 메뉴"}
        className="flex flex-col gap-1"
      >
        {navItems.map((item) => (
          <button
            key={item.key}
            type="button"
            aria-current={item.active ? "page" : undefined}
            onClick={item.onClick}
            className={`${NAV_ITEM_CLASS} ${
              item.active ? "bg-brand text-white" : "text-ink hover:bg-chip"
            }`}
          >
            <item.icon size={16} className={item.active ? "text-white" : "text-brand"} />
            {item.label}
          </button>
        ))}
      </nav>

      {/* 2. 언어 */}
      <section className="flex flex-col gap-1.5">
        <h2 className="text-xs font-bold text-label">
          {state.language === "en" ? "Language" : "언어"}
        </h2>
        <div className="grid grid-cols-2 gap-1.5">
          {LANGUAGES.map((lang) => (
            <button
              key={lang.code}
              type="button"
              aria-pressed={state.language === lang.code}
              onClick={() => dispatch({ type: "SET_LANGUAGE", payload: lang.code })}
              className={`rounded-lg px-2.5 py-2 text-sm font-medium transition-colors ${
                state.language === lang.code
                  ? "bg-brand text-white"
                  : "bg-chip text-ink hover:bg-sky-light"
              }`}
            >
              {lang.label}
            </button>
          ))}
        </div>
      </section>

      {/* 4. 채팅 히스토리 */}
      <section className="flex flex-col gap-1.5">
        <h2 className="text-xs font-bold text-label">{isEn ? "Chat history" : "채팅 히스토리"}</h2>
        {history.length === 0 ? (
          <p className="py-1 text-xs text-muted">
            {isEn ? "No conversations yet" : "아직 대화 기록이 없어요"}
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {history.map((entry) => {
              /*
               * 지금 보고 있는 대화. 목록에 여러 줄이 있는데 어느 것이 열려
               * 있는지 표시가 없으면, 대화를 이어가면서도 자기가 어디 있는지
               * 모른다. 홈처럼 세션이 없는 화면에서는 아무 줄도 켜지지 않는다.
               */
              const isCurrent = state.session_id === entry.id;
              return (
                <li
                  key={entry.id}
                  aria-current={isCurrent ? "true" : undefined}
                  className={`relative rounded-xl px-3 py-2 ${
                    isCurrent ? "bg-chip" : "hover:bg-chip"
                  }`}
                >
                  {renaming === entry.id ? (
                    <input
                      ref={renameInputRef}
                      aria-label={isEn ? "Conversation name" : "대화 이름"}
                      value={renameDraft}
                      onChange={(event) => setRenameDraft(event.target.value)}
                      onBlur={() => commitRename(entry.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") commitRename(entry.id);
                        if (event.key === "Escape") setRenaming(null);
                      }}
                      className="w-full rounded-md border border-border px-2 py-1 text-sm"
                    />
                  ) : (
                    <div className="flex items-start justify-between gap-2">
                      {/* 한 줄 전체가 버튼이다 — 제목만 누를 수 있게 하면 날짜·장소
                        쪽을 눌렀을 때 아무 일도 안 나 고장으로 보인다. */}
                      <button
                        type="button"
                        aria-label={
                          isEn ? `Open conversation ${entry.label}` : `${entry.label} 대화 열기`
                        }
                        onClick={() => openConversation(entry.id)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <p
                          className={`truncate text-sm text-ink ${
                            isCurrent ? "font-bold" : "font-medium"
                          }`}
                        >
                          {entry.label}
                        </p>
                        <p className="truncate text-xs text-muted">
                          {entry.date}
                          {entry.location && (
                            <>
                              {" · "}
                              <span className="text-brand">{entry.location}</span>
                            </>
                          )}
                        </p>
                      </button>
                      <button
                        type="button"
                        aria-label={isEn ? `${entry.label} menu` : `${entry.label} 메뉴`}
                        onClick={() => setOpenMenu((open) => (open === entry.id ? null : entry.id))}
                        className="shrink-0 text-muted hover:text-ink"
                      >
                        <MoreHorizontal size={15} />
                      </button>
                    </div>
                  )}

                  {openMenu === entry.id && (
                    <>
                      <button
                        type="button"
                        aria-label={isEn ? "Close menu" : "메뉴 닫기"}
                        onClick={() => setOpenMenu(null)}
                        className="fixed inset-0 z-20 cursor-default"
                      />
                      <div
                        role="menu"
                        className="absolute right-0 top-full z-30 flex w-36 flex-col gap-0.5 rounded-2xl bg-white p-1.5 shadow-card"
                      >
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setRenameDraft(entry.label);
                            setRenaming(entry.id);
                            setOpenMenu(null);
                          }}
                          className="rounded-xl px-3 py-2 text-left text-sm font-medium text-ink transition-colors hover:bg-chip"
                        >
                          {isEn ? "Rename" : "이름 바꾸기"}
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            /* 목록에서 한 줄을 지우는 것이 곧 그 대화를 지우는
                             것이다. 화면에서 먼저 빼고 서버에 보낸다. */
                            setHistory((prev) => prev.filter((item) => item.id !== entry.id));
                            setOpenMenu(null);
                            /*
                             * 지금 보고 있는 대화를 지웠으면 화면도 비운다.
                             * 두지 않으면 지운 대화가 그대로 남아 있고, 이어
                             * 물으면 없는 session_id가 나가 백엔드가 조용히 새
                             * 세션을 만든다 — 사용자는 같은 대화를 이어간 줄로
                             * 안다. 오던 답변도 그 대화의 것이라 화면에서 뗀다.
                             */
                            if (state.session_id === entry.id) {
                              detachChatRequest();
                              dispatch({ type: "RESET" });
                            }
                            void deleteChatSession(entry.id).catch(() => {
                              void refreshChatSessions().then(setHistory);
                            });
                          }}
                          className="rounded-xl px-3 py-2 text-left text-sm font-medium text-rust transition-colors hover:bg-chip"
                        >
                          {isEn ? "Delete" : "삭제"}
                        </button>
                      </div>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/*
        6. 계정 — 로그인 여부로 자리가 갈린다.

        - **로그인 안 한 상태(게스트)**: "로그인" 버튼 하나다(2026-09-06). 진입이
          게스트로 자동으로 열리게 바뀌면서(`RequireUser`) 여기가 로그인으로 가는
          유일한 입구가 됐다. 신원 표시를 그리지 않는 이유는, 게스트에게 보여줄
          것이 "게스트 / 게스트로 이용 중"뿐이라 이름 자리를 차지하고도 아무것도
          알려주지 못하기 때문이다 — 그 자리에는 할 수 있는 동작이 오는 게 낫다.
        - **계정**: 아바타+이름 버튼 하나를 두고 나머지는 눌렀을 때 팝업으로 낸다
          (2026-09-04). 예전에는 신원 라벨 한 줄 + "계정 만들기" + "로그아웃"이 모두
          바닥에 펼쳐져 있었다 — 라벨이 `identityLabel`이라 **이메일이 상시 노출**됐고
          (이름이 있어도 이메일이 먼저 걸린다), **되돌릴 수 없는 로그아웃이 상시
          눌리는 자리**에 있었다.

        게스트용 "계정 만들기" 줄은 팝업에서 **뺐다**(2026-09-06). 게스트는 이제 이
        팝업 자체를 보지 않고, 가입은 로그인 화면의 "회원가입" 링크로 닿는다 —
        그 화면이 게스트 세션을 그대로 승격시킨다(AuthContext.signUpWithEmail).

        팝업에 "프로필"·"설정"·"도움말" 줄은 만들지 않는다. 그 화면이 없다 —
        라우트는 /, /chat, /preferences, /location, /schedule 뿐이다. 없는 화면
        이름을 메뉴에 만들면 눌러도 아무 일이 일어나지 않는다: 언어를 中文까지
        그리지 않은 것과 같은 이유다(LANGUAGES 주석).
      */}
      <div className="relative mt-auto">
        {status === "ready" &&
          session &&
          identity &&
          (isGuest ? (
            /* 목적지를 state로 실어 보낸다 — 로그인을 마쳤을 때 홈이 아니라 보던
               화면으로 돌아온다. LoginPage가 이 값을 `from`으로 읽는다. */
            <button
              type="button"
              onClick={() => {
                navigate("/login", { state: { from: location.pathname } });
                onNavigate?.();
              }}
              className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm font-semibold text-ink transition-colors hover:bg-chip"
            >
              <LogIn size={17} aria-hidden />
              {isEn ? "Sign in" : "로그인"}
            </button>
          ) : (
            <>
              {accountMenuOpen && (
                <>
                  {/* 대화 줄 메뉴와 같은 방식이다 — 바깥을 누르면 닫힌다. */}
                  <button
                    type="button"
                    aria-label={isEn ? "Close account menu" : "계정 메뉴 닫기"}
                    onClick={closeAccountMenu}
                    className="fixed inset-0 z-20 cursor-default"
                  />
                  {/* 계정 버튼이 사이드바 맨 아래라 위로 띄운다(bottom-full). */}
                  <div className="absolute bottom-full left-0 right-0 z-30 mb-2 flex flex-col rounded-2xl bg-white p-1.5 shadow-card">
                    {/* 어느 계정의 메뉴인지 팝업 안에서도 보인다 — 팝업이 계정
                      버튼을 덮는 자리에 뜨기 때문이다. 누를 수는 없다(계정
                      화면이 없다). */}
                    <div className="flex items-center gap-2.5 px-2 py-2">
                      <IdentityRow identity={identity} />
                    </div>
                    <div className="mx-2 my-1 h-px bg-border" />
                    {/* role="menu" 는 menuitem 만 감싼다 — 위의 신원 헤더는
                      menuitem 이 아니다. */}
                    <div
                      role="menu"
                      aria-label={isEn ? "Account" : "계정"}
                      className="flex flex-col"
                    >
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => void handleSignOut()}
                        className={`${ACCOUNT_MENU_ITEM_CLASS} text-rust hover:bg-chip`}
                      >
                        <LogOut size={15} aria-hidden />
                        {isEn ? "Sign out" : "로그아웃"}
                      </button>
                    </div>
                  </div>
                </>
              )}
              {/* 이름을 읽어주는 것이 이 버튼의 이름이다 — aria-label로 "계정 메뉴"라고
                덮으면 어느 계정인지 소리로 확인할 방법이 없어진다. 무엇이 열리는지는
                aria-haspopup이 알린다. */}
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={accountMenuOpen}
                onClick={() => setAccountMenuOpen((open) => !open)}
                className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left transition-colors hover:bg-chip"
              >
                <IdentityRow identity={identity} />
              </button>
            </>
          ))}
      </div>
    </div>
  );
}
