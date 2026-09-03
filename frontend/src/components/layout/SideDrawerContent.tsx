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
import { Home, LogOut, MapPin, MoreHorizontal, Plus, Route, Sparkles, Trash2 } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { identityLabel } from "../../auth/identityLabel";
import { discardChatRequest } from "../../state/chatAbortController";
import { sheetState } from "../../state/sheetNav";
import { useTripDispatch, useTripState } from "../../state/TripContext";
import type { Language } from "../../types";
import { deleteChatSession, renameChatSession, resumeChatSession } from "../../api/trip";
import { loadChatSessions, refreshChatSessions } from "../../state/chatSessions";
import {
  createId,
  loadFavorites,
  saveFavorites,
  type ChatHistoryEntry,
  type FavoritePlace,
} from "../../state/sidebarStorage";
import { AddFavoriteModal } from "./AddFavoriteModal";

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
  const { session, status, signOut } = useAuth();

  const [favorites, setFavorites] = useState<FavoritePlace[]>(() => loadFavorites());
  /*
   * 채팅 히스토리는 계정에서 온다(GET /api/sessions). 예전에는 localStorage
   * 목업이었는데 **항목을 넣는 코드가 아예 없어** 늘 비어 있었다.
   *
   * 로컬 거울을 두지 않는다 — 취향(preferenceSync)과 다른 점이다. 취향은 게스트가
   * 가입할 때 넘겨줘야 할 값이지만, 대화는 이미 서버에 있고 그 세션의 소유자도
   * 서버가 안다. 목록만 로컬에 복사해두면 지운 대화가 되살아나는 쪽이 더 나쁘다.
   */
  const [history, setHistory] = useState<ChatHistoryEntry[]>([]);
  const [showAddFavorite, setShowAddFavorite] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => saveFavorites(favorites), [favorites]);

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
    if (renamingId) renameInputRef.current?.focus();
  }, [renamingId]);

  const hasConversation = state.messages.length > 0;

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
       오던 답변이 그 빈 화면에 붙으면 안 된다. */
    discardChatRequest();
    dispatch({ type: "RESET" });
    navigate("/");
    onNavigate?.();
  }

  async function handleSignOut() {
    try {
      await signOut();
      /* 신원만 끊고 대화를 두면 다음 신원의 화면에 이전 대화가 남는다. 함께 비운다. */
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
    /* 답변이 오는 중에 다른 대화를 열면 그 답변이 여기 붙는다. 화면을 바꾸기
       전에 진행 중인 요청을 버린다. */
    discardChatRequest();
    try {
      const detail = await resumeChatSession(sessionId);
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
         응답을 기다리는 동안 입력칸을 붙잡아 둘 이유가 없다. */
      setHistory((prev) =>
        prev.map((item) => (item.id === id ? { ...item, label: trimmed } : item)),
      );
      void renameChatSession(id, trimmed).catch(() => {
        /* 실패하면 서버 값으로 되돌린다 — 바뀐 척 남겨두면 다음에 열었을 때
           예전 이름이 돌아와 있어 더 혼란스럽다. */
        void refreshChatSessions().then(setHistory);
      });
    }
    setRenamingId(null);
  }

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
      label: "홈",
      icon: Home,
      active: pathname === "/" && !hasConversation,
      onClick: goHome,
    },
    {
      key: "preferences",
      label: "취향 설정",
      icon: Sparkles,
      active: pathname === "/preferences",
      onClick: () => go("/preferences"),
    },
    {
      key: "location",
      label: "위치 설정",
      icon: MapPin,
      active: pathname === "/location",
      onClick: () => go("/location", { sheet: true }),
    },
    {
      key: "schedule",
      label: "일정",
      icon: Route,
      active: pathname === "/schedule",
      onClick: () => go("/schedule", { sheet: true }),
    },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 pb-5">
      {/* 1. 내비게이션 */}
      <nav aria-label="주요 메뉴" className="flex flex-col gap-1">
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
        <h2 className="text-xs font-bold text-label">언어</h2>
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
          <h2 className="text-xs font-bold text-label">즐겨찾기</h2>
          <button
            type="button"
            onClick={() => setShowAddFavorite(true)}
            className="flex items-center gap-0.5 text-xs font-semibold text-brand transition-colors hover:text-brand-deep"
          >
            <Plus size={12} aria-hidden /> 추가
          </button>
        </div>
        {favorites.length === 0 ? (
          <p className="py-1 text-xs text-muted">등록된 즐겨찾기가 없어요</p>
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
        <h2 className="text-xs font-bold text-label">채팅 히스토리</h2>
        {history.length === 0 ? (
          <p className="py-1 text-xs text-muted">아직 대화 기록이 없어요</p>
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
                  {renamingId === entry.id ? (
                    <input
                      ref={renameInputRef}
                      aria-label="대화 이름"
                      value={renameDraft}
                      onChange={(event) => setRenameDraft(event.target.value)}
                      onBlur={() => commitRename(entry.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") commitRename(entry.id);
                        if (event.key === "Escape") setRenamingId(null);
                      }}
                      className="w-full rounded-md border border-border px-2 py-1 text-sm"
                    />
                  ) : (
                    <div className="flex items-start justify-between gap-2">
                      {/* 한 줄 전체가 버튼이다 — 제목만 누를 수 있게 하면 날짜·장소
                        쪽을 눌렀을 때 아무 일도 안 나 고장으로 보인다. */}
                      <button
                        type="button"
                        aria-label={`${entry.label} 대화 열기`}
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
                        aria-label={`${entry.label} 메뉴`}
                        onClick={() => setOpenMenuId((id) => (id === entry.id ? null : entry.id))}
                        className="shrink-0 text-muted hover:text-ink"
                      >
                        <MoreHorizontal size={15} />
                      </button>
                    </div>
                  )}

                  {openMenuId === entry.id && (
                    <>
                      <button
                        type="button"
                        aria-label="메뉴 닫기"
                        onClick={() => setOpenMenuId(null)}
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
                            setRenamingId(entry.id);
                            setOpenMenuId(null);
                          }}
                          className="rounded-xl px-3 py-2 text-left text-sm font-medium text-ink transition-colors hover:bg-chip"
                        >
                          이름 바꾸기
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            /* 목록에서 한 줄을 지우는 것이 곧 그 대화를 지우는
                             것이다. 화면에서 먼저 빼고 서버에 보낸다. */
                            setHistory((prev) => prev.filter((item) => item.id !== entry.id));
                            setOpenMenuId(null);
                            void deleteChatSession(entry.id).catch(() => {
                              void refreshChatSessions().then(setHistory);
                            });
                          }}
                          className="rounded-xl px-3 py-2 text-left text-sm font-medium text-rust transition-colors hover:bg-chip"
                        >
                          삭제
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

      {/* 5. 신원 라벨 + 로그아웃 — 맨 아래 */}
      <div className="mt-auto flex flex-col items-start gap-1">
        {status === "ready" && session && (
          <p className="px-1 text-xs text-muted">{identityLabel(session)}</p>
        )}
        <button
          type="button"
          onClick={() => void handleSignOut()}
          className="flex items-center gap-2 self-start px-1 py-2 text-sm font-medium text-muted transition-colors hover:text-rust"
        >
          <LogOut size={15} aria-hidden /> 로그아웃
        </button>
      </div>

      {showAddFavorite && (
        <AddFavoriteModal
          onAdd={(label) => setFavorites((prev) => [...prev, { id: createId("fav"), label }])}
          onClose={() => setShowAddFavorite(false)}
        />
      )}
    </div>
  );
}
