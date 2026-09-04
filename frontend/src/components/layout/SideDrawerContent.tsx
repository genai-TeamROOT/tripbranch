/*
 * 역할: 사이드바/드로어 안에 들어가는 내용. 내비게이션·언어·즐겨찾기·히스토리·로그아웃.
 * 입력: 현재 라우트, TripContext 언어/메시지 상태, localStorage의 즐겨찾기·히스토리.
 * 출력: 라우트 이동, 언어 변경, 목록 편집, 로그아웃.
 * 호출 시점: DesktopSidebar(768px 이상 상시 패널)와 모바일 드로어가 공유한다.
 *   컨테이너만 다르고 내용은 하나다 — 두 번 만들지 않는다(DESIGN_SYSTEM.md 6.17).
 * 근거: package_D/DESIGN_SYSTEM.md §6.17.
 */

import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Home,
  LogOut,
  MapPin,
  MoreHorizontal,
  Plus,
  Route,
  Sparkles,
  Trash2,
  UserPlus,
} from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { identityLabel, isGuestSession } from "../../auth/identityLabel";
import { detachChatRequest } from "../../state/chatAbortController";
import { sheetState } from "../../state/sheetNav";
import { useTripDispatch, useTripState } from "../../state/TripContext";
import type { Language } from "../../types";
import {
  deleteChatSession,
  deleteSavedSchedule,
  renameChatSession,
  renameSavedSchedule,
  resumeChatSession,
} from "../../api/trip";
import { loadChatSessions, refreshChatSessions } from "../../state/chatSessions";
import { clearLocalUserData } from "../../state/localUserData";
import { useFavorites } from "../../hooks/useFavorites";
import {
  loadSavedSchedules,
  refreshSavedSchedules,
  subscribeSavedSchedules,
  type SavedScheduleEntry,
} from "../../state/savedSchedules";
import { type ChatHistoryEntry } from "../../state/sidebarStorage";

/*
 * 사이드바에는 줄마다 메뉴가 붙는 목록이 둘이다 — 대화와 저장한 일정. 어느
 * 목록의 어느 줄인지를 함께 들고 있어야 한쪽을 열 때 다른 쪽이 닫힌다.
 * `openMenu` 주석 참고.
 */
type MenuTarget = { kind: "chat" | "schedule"; id: string };

function isTarget(target: MenuTarget | null, kind: MenuTarget["kind"], id: string): boolean {
  return target !== null && target.kind === kind && target.id === id;
}

interface SideDrawerContentProps {
  /** 모바일 드로어에서만 넘긴다 — 링크를 누르면 드로어를 닫기 위해서다. */
  onNavigate?: () => void;
}

const NAV_ITEM_CLASS =
  "flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm font-semibold transition-colors";

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

  const [favorites, setFavorites] = useFavorites();
  /*
   * 채팅 히스토리는 계정에서 온다(GET /api/sessions). 예전에는 localStorage
   * 목업이었는데 **항목을 넣는 코드가 아예 없어** 늘 비어 있었다.
   *
   * 로컬 거울을 두지 않는다 — 취향(preferenceSync)과 다른 점이다. 취향은 게스트가
   * 가입할 때 넘겨줘야 할 값이지만, 대화는 이미 서버에 있고 그 세션의 소유자도
   * 서버가 안다. 목록만 로컬에 복사해두면 지운 대화가 되살아나는 쪽이 더 나쁘다.
   */
  const [history, setHistory] = useState<ChatHistoryEntry[]>([]);
  /* 저장한 일정도 계정에서 온다(GET /api/schedules). 대화 목록과 별도 저장소라
     따로 받는다 — 세션이 30일 뒤 정리돼도 이쪽은 남는다. */
  const [schedules, setSchedules] = useState<SavedScheduleEntry[]>([]);
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
  const [openMenu, setOpenMenu] = useState<MenuTarget | null>(null);
  const [renaming, setRenaming] = useState<MenuTarget | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  /* 게스트 로그아웃은 되돌릴 수 없어 한 번 끊는다 — handleSignOut 주석 참고. */
  const [confirmingSignOut, setConfirmingSignOut] = useState(false);
  const renameInputRef = useRef<HTMLInputElement>(null);


  useEffect(() => {
    let active = true;
    void loadChatSessions().then((entries) => {
      if (active) setHistory(entries);
    });
    void loadSavedSchedules().then((entries) => {
      if (active) setSchedules(entries);
    });
    /* 일정을 저장하면 목록이 바로 바뀐다. 대화 목록처럼 TripContext 상태를 볼 수
       없는 이유는 savedSchedules.subscribeSavedSchedules 주석에 있다. */
    const unsubscribe = subscribeSavedSchedules(setSchedules);
    return () => {
      active = false;
      unsubscribe();
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

  function go(path: string, options?: { sheet?: boolean }) {
    // 위치·일정은 새 페이지가 아니라 지금 화면 위에 바텀시트로 뜬다(§5) — 지금
    // location을 backgroundLocation으로 실어 보내야 닫았을 때 여기로 돌아온다.
    navigate(path, options?.sheet ? { state: sheetState(location) } : undefined);
    onNavigate?.();
  }

  /*
   * "홈"만 활성 판정이 다르다. 대화가 남아 있으면 라우트가 "/"여도 비활성으로 그린다.
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
   * 게스트에게 로그아웃은 되돌릴 수 없다 — 다시 로그인할 수단이 없어 그 uid로
   * 돌아갈 길이 사라지고, 그 uid에 달린 대화·보관함도 함께 닿을 수 없게 된다
   * (AuthContext.signOut 주석과 같은 근거). 그래서 게스트일 때만 한 번 끊는다.
   *
   * 계정 사용자는 확인을 받지 않는다. 다시 로그인하면 그대로 돌아오므로, 되돌릴 수
   * 있는 동작에까지 확인을 붙이면 확인이라는 신호 자체가 값싸진다.
   *
   * AuthStatusBadge가 이미 같은 확인을 갖고 있는데 그 배지는 개발자 화면에서만
   * 쓰인다. 사용자가 실제로 누르는 것은 이쪽 버튼이었고, 여기엔 확인이 없었다.
   */
  async function handleSignOut() {
    if (session && isGuestSession(session) && !confirmingSignOut) {
      setConfirmingSignOut(true);
      return;
    }
    try {
      await signOut();
      /* 신원만 끊고 이 기기의 데이터를 두면 다음 신원의 화면에 앞사람의 대화·취향·
         즐겨찾기·검색 위치가 그대로 남는다. 함께 비운다(state/localUserData.ts). */
      clearLocalUserData();
      dispatch({ type: "RESET" });
      /* 이동은 따로 시키지 않는다 — 세션이 사라지면 RequireUser가 관문으로 보낸다. */
    } finally {
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

  function commitRename(target: MenuTarget) {
    const trimmed = renameDraft.trim();
    if (trimmed) {
      /* 화면을 먼저 바꾸고 서버에 보낸다 — 이름 바꾸기는 되돌릴 수 있는 동작이라
         응답을 기다리는 동안 입력칸을 붙잡아 둘 이유가 없다. 실패하면 서버 값으로
         되돌린다 — 바뀐 척 남겨두면 다음에 열었을 때 예전 이름이 돌아와 있어 더
         혼란스럽다. 두 목록이 같은 규칙을 쓴다. */
      if (target.kind === "chat") {
        setHistory((prev) =>
          prev.map((item) => (item.id === target.id ? { ...item, label: trimmed } : item)),
        );
        void renameChatSession(target.id, trimmed).catch(() => {
          void refreshChatSessions().then(setHistory);
        });
      } else {
        setSchedules((prev) =>
          prev.map((item) => (item.id === target.id ? { ...item, label: trimmed } : item)),
        );
        void renameSavedSchedule(target.id, trimmed).catch(() => {
          void refreshSavedSchedules();
        });
      }
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
      label: state.language === "en" ? "Home" : "홈",
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
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 pb-5">
      {/* 1. 내비게이션 */}
      <nav aria-label={state.language === "en" ? "Main menu" : "주요 메뉴"} className="flex flex-col gap-1">
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
        <h2 className="text-xs font-bold text-label">{state.language === "en" ? "Language" : "언어"}</h2>
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

      {/* 3. 즐겨찾기 */}
      <section className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-bold text-label">{state.language === "en" ? "Favorites" : "즐겨찾기"}</h2>
          {/* 즐겨찾기는 검색해서 담는다 — 여기서 이름만 받으면 좌표도 주소도 없어
              위치로 쓸 수 없다. 검색이 있는 위치 설정 화면으로 보낸다. */}
          <button
            type="button"
            onClick={() => go("/location", { sheet: true })}
            className="flex items-center gap-0.5 text-xs font-semibold text-brand transition-colors hover:text-brand-deep"
          >
            <Plus size={12} aria-hidden /> {state.language === "en" ? "Add" : "추가"}
          </button>
        </div>
        {favorites.length === 0 ? (
          <p className="py-1 text-xs text-muted">
            {state.language === "en" ? "No favorites yet" : "등록된 즐겨찾기가 없어요"}
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {favorites.map((favorite) => (
              <li
                key={favorite.id}
                className="group flex items-center gap-2 rounded-xl px-3 py-2 hover:bg-chip"
              >
                <MapPin size={14} className="shrink-0 text-gold" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-sm text-ink">{favorite.label}</span>
                <button
                  type="button"
                  aria-label={`${favorite.label} 즐겨찾기 삭제`}
                  onClick={() =>
                    setFavorites((prev) => prev.filter((item) => item.id !== favorite.id))
                  }
                  className="shrink-0 text-muted opacity-0 transition-opacity hover:text-rust group-hover:opacity-100"
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
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
                  {isTarget(renaming, "chat", entry.id) ? (
                    <input
                      ref={renameInputRef}
                      aria-label={isEn ? "Conversation name" : "대화 이름"}
                      value={renameDraft}
                      onChange={(event) => setRenameDraft(event.target.value)}
                      onBlur={() => commitRename({ kind: "chat", id: entry.id })}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") commitRename({ kind: "chat", id: entry.id });
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
                        aria-label={isEn ? `Open conversation ${entry.label}` : `${entry.label} 대화 열기`}
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
                        onClick={() =>
                          setOpenMenu((open) =>
                            isTarget(open, "chat", entry.id) ? null : { kind: "chat", id: entry.id },
                          )
                        }
                        className="shrink-0 text-muted hover:text-ink"
                      >
                        <MoreHorizontal size={15} />
                      </button>
                    </div>
                  )}

                  {isTarget(openMenu, "chat", entry.id) && (
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
                            setRenaming({ kind: "chat", id: entry.id });
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
        5. 저장한 일정 (SCHEDULE 카드 2)

        채팅 히스토리 **아래**에 둔다. 대화가 일정보다 먼저 생기고 개수도 많아,
        위에 두면 대화 목록이 접힌 화면에서 스크롤 밖으로 밀린다.

        이름 바꾸기·삭제 메뉴는 대화 쪽과 **같은 상태를 공유하되 목록을 구분한다**
        (`MenuTarget`). 상태를 두 벌 만들지 않은 이유는 openMenu 주석에 있다.
      */}
      <section className="flex flex-col gap-1.5">
        <h2 className="text-xs font-bold text-label">{isEn ? "Saved schedules" : "저장한 일정"}</h2>
        {schedules.length === 0 ? (
          <p className="py-1 text-xs text-muted">
            {isEn ? "No saved schedules yet" : "아직 저장한 일정이 없어요"}
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {schedules.map((entry) => (
              <li key={entry.id} className="relative rounded-xl px-2.5 py-2 hover:bg-chip">
                {isTarget(renaming, "schedule", entry.id) ? (
                  <input
                    ref={renameInputRef}
                    aria-label={isEn ? "Schedule name" : "일정 이름"}
                    value={renameDraft}
                    onChange={(event) => setRenameDraft(event.target.value)}
                    onBlur={() => commitRename({ kind: "schedule", id: entry.id })}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") commitRename({ kind: "schedule", id: entry.id });
                      if (event.key === "Escape") setRenaming(null);
                    }}
                    className="w-full rounded-md border border-border px-2 py-1 text-sm"
                  />
                ) : (
                  <div className="flex items-start justify-between gap-2">
                    {/* 대화 목록과 같은 이유로 한 줄 전체가 버튼이다 — 날짜 쪽을
                      눌렀을 때 아무 일도 안 나면 고장으로 보인다. */}
                    <button
                      type="button"
                      aria-label={isEn ? `Open schedule ${entry.label}` : `${entry.label} 일정 열기`}
                      onClick={() =>
                        go(`/schedule?saved=${encodeURIComponent(entry.id)}`, { sheet: true })
                      }
                      className="min-w-0 flex-1 text-left"
                    >
                      <p className="truncate text-sm font-medium text-ink">{entry.label}</p>
                      {entry.date && (
                        <p className="truncate text-[11px] text-muted">
                          {isEn ? `Saved ${entry.date}` : `${entry.date} 저장`}
                        </p>
                      )}
                    </button>
                    <button
                      type="button"
                      aria-label={isEn ? `${entry.label} menu` : `${entry.label} 메뉴`}
                      onClick={() =>
                        setOpenMenu((open) =>
                          isTarget(open, "schedule", entry.id)
                            ? null
                            : { kind: "schedule", id: entry.id },
                        )
                      }
                      className="shrink-0 text-muted hover:text-ink"
                    >
                      <MoreHorizontal size={15} />
                    </button>
                  </div>
                )}

                {isTarget(openMenu, "schedule", entry.id) && (
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
                          setRenaming({ kind: "schedule", id: entry.id });
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
                          /* 화면에서 먼저 빼고 서버에 보낸다(대화 삭제와 같은 규칙).
                             실패하면 서버 목록으로 되돌린다. */
                          setSchedules((prev) => prev.filter((item) => item.id !== entry.id));
                          setOpenMenu(null);
                          void deleteSavedSchedule(entry.id).catch(() => {
                            void refreshSavedSchedules();
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
            ))}
          </ul>
        )}
      </section>

      {/* 6. 신원 라벨 + 계정 만들기(게스트만) + 로그아웃 — 맨 아래 */}
      <div className="mt-auto flex flex-col items-start gap-1">
        {status === "ready" && session && (
          <p className="px-1 text-xs text-muted">{identityLabel(session, state.language)}</p>
        )}
        {/*
          게스트에게만 보인다. **이 버튼이 없으면 승계 경로에 닿을 방법이 없었다** —
          /signup으로 가는 링크가 로그인 관문에만 있는데 게스트는 세션이 있어서 그
          화면으로 못 들어간다(LoginPage의 Navigate). 그래서 가입하려면 먼저
          로그아웃해야 했고, 로그아웃하면 그 uid로 돌아갈 길이 없어 이어받을 기록
          자체가 사라졌다.

          문구를 "로그인"이 아니라 "계정 만들기"로 둔다. 게스트에게 필요한 동작은
          지금 쓰던 것을 계정으로 굳히는 것이지 다른 계정으로 갈아타는 것이 아니고,
          가입 화면이 게스트 세션을 그대로 승격시킨다(AuthContext.signUpWithEmail).
        */}
        {isGuest && (
          <button
            type="button"
            onClick={() => go("/signup")}
            className="flex items-center gap-2 self-start px-1 py-2 text-sm font-medium text-muted transition-colors hover:text-brand"
          >
            <UserPlus size={15} aria-hidden /> {isEn ? "Create account" : "계정 만들기"}
          </button>
        )}
        {confirmingSignOut ? (
          /* 잃는 것과 대신 할 수 있는 것을 함께 말한다. "정말 하시겠어요?"만 물으면
             사용자는 무엇을 잃는지 모른 채 고른다. */
          <div className="flex flex-col items-start gap-2 px-1 py-2">
            <p role="alert" className="text-xs text-rust">
              {isEn
                ? "Signing out means you won't be able to return to your past conversations. Create an account to keep using them."
                : "로그아웃하면 지금까지의 대화로 돌아올 수 없어요. 계정을 만들면 그대로 이어서 쓸 수 있어요."}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void handleSignOut()}
                className="rounded px-2 py-1 text-sm font-medium text-rust"
              >
                {isEn ? "Sign out" : "로그아웃"}
              </button>
              <button
                type="button"
                onClick={() => setConfirmingSignOut(false)}
                className="rounded px-2 py-1 text-sm font-medium text-muted"
              >
                {isEn ? "Cancel" : "취소"}
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => void handleSignOut()}
            className="flex items-center gap-2 self-start px-1 py-2 text-sm font-medium text-muted transition-colors hover:text-rust"
          >
            <LogOut size={15} aria-hidden /> {isEn ? "Sign out" : "로그아웃"}
          </button>
        )}
      </div>

    </div>
  );
}
