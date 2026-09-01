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
import { sheetState } from "../../state/sheetNav";
import { useTripDispatch, useTripState } from "../../state/TripContext";
import type { Language } from "../../types";
import {
  createId,
  loadChatHistory,
  loadFavorites,
  saveChatHistory,
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
  const [history, setHistory] = useState<ChatHistoryEntry[]>(() => loadChatHistory());
  const [showAddFavorite, setShowAddFavorite] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => saveFavorites(favorites), [favorites]);
  useEffect(() => saveChatHistory(history), [history]);
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

  function commitRename(id: string) {
    const trimmed = renameDraft.trim();
    if (trimmed) {
      setHistory((prev) =>
        prev.map((item) => (item.id === id ? { ...item, label: trimmed } : item)),
      );
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
            {history.map((entry) => (
              <li key={entry.id} className="relative rounded-xl px-3 py-2 hover:bg-chip">
                {renamingId === entry.id ? (
                  <input
                    ref={renameInputRef}
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
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink">{entry.label}</p>
                      <p className="truncate text-xs text-muted">
                        {entry.date}
                        {entry.placeName && (
                          <>
                            {" · "}
                            <span className="text-brand">{entry.placeName}</span>
                          </>
                        )}
                      </p>
                    </div>
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
                          setHistory((prev) => prev.filter((item) => item.id !== entry.id));
                          setOpenMenuId(null);
                        }}
                        className="rounded-xl px-3 py-2 text-left text-sm font-medium text-rust transition-colors hover:bg-chip"
                      >
                        삭제
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))}
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
