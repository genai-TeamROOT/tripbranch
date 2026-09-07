/*
 * 역할: 계정에 저장한 일정 목록 — 검색·날짜로 훑어보기, 열기·이름 바꾸기·삭제.
 * 입력: 없다(계정에서 직접 받아온다, GET /api/schedules).
 * 출력: `?saved=<id>`로의 이동, 이름 변경·삭제 요청.
 * 호출 시점: SchedulePage가 화면 아래에 렌더한다.
 *
 * **원래 사이드바(`SideDrawerContent` §5)에 있었다**(2026-09-04, lth2295, PR #369).
 * 일정 탭이 이미 있는데 목록만 사이드바에 있어서, 일정을 관리하려면 화면을 벗어나야
 * 했다. 목록을 이 컴포넌트로 떼어 일정 화면으로 옮겼다.
 *
 * 사이드바에 있을 때는 대화 목록과 메뉴·이름변경 상태를 **한 벌로 공유**했다
 * (`MenuTarget = { kind, id }`) — 한 번에 하나만 열려야 하는데 상태를 두 벌 두면
 * 대화 메뉴를 열어둔 채 일정 메뉴도 열렸기 때문이다. 분리하면 그 이유가 사라져
 * `id` 하나만 든다.
 *
 * **검색·달력 필터는 순수 프론트 필터다**(2026-09-07). `GET /api/schedules`는
 * 제목·날짜만 주고 장소 사진은 없어서, 카드 아이콘은 실제 장소 사진이 아니라
 * 고정 아이콘이다 — 실제 사진을 쓰려면 B(`state/`) 쪽에 필드가 필요하다.
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MoreHorizontal, Search } from "lucide-react";
import { deleteSavedSchedule, renameSavedSchedule } from "../../api/trip";
import { useAuth } from "../../auth/AuthContext";
import { identityDisplay } from "../../auth/identityLabel";
import { IdentityAvatar } from "../layout/SidebarAccount";
import { useSavedSchedules } from "../../hooks/useSavedSchedules";
import { refreshSavedSchedules, type SavedScheduleEntry } from "../../state/savedSchedules";
import { useTripState } from "../../state/TripContext";
import { ScheduleCalendarStrip } from "./ScheduleCalendarStrip";
import { startOfWeek, toDateKey } from "../../utils/scheduleDates";

function matchesQuery(label: string, query: string): boolean {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return true;
  return label.toLowerCase().includes(trimmed);
}

function matchesDate(createdAt: Date | null, selectedDateKey: string | null): boolean {
  if (!selectedDateKey) return true;
  return createdAt !== null && toDateKey(createdAt) === selectedDateKey;
}

export function SavedScheduleList() {
  const navigate = useNavigate();
  const isEn = useTripState().language === "en";
  const { session } = useAuth();
  /* 카드 아이콘은 고정 아이콘 대신 계정 아바타를 쓴다(2026-09-07) — 목록의
     일정들이 전부 이 계정 것이라 "누구의 것인지"를 보여주는 게 더 쓸모있다.
     RequireUser가 이 화면 앞에서 이미 세션(게스트 포함)을 보장하지만, 타입상
     null일 수 있어 없을 때는 그리지 않는다. */
  const identity = session ? identityDisplay(session, isEn ? "en" : "ko") : null;
  const [query, setQuery] = useState("");
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [selectedDateKey, setSelectedDateKey] = useState<string | null>(null);

  /*
   * 서버 목록은 훅이 들고, 여기서는 그것을 지역 상태로 받아 **낙관적 편집**(이름
   * 바꾸기·삭제)을 얹는다. 훅 값을 바로 그리면 이름을 바꾼 순간이 아니라 서버
   * 응답이 온 뒤에야 화면이 바뀐다.
   */
  const loaded = useSavedSchedules();
  const [schedules, setSchedules] = useState<SavedScheduleEntry[]>([]);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (loaded) setSchedules(loaded);
  }, [loaded]);

  /* 원본(사이드바)과 같은 동작이다 — 이름 바꾸기를 누르면 바로 입력할 수 있어야 한다. */
  useEffect(() => {
    if (renaming) renameInputRef.current?.focus();
  }, [renaming]);

  function commitRename(id: string) {
    const trimmed = renameDraft.trim();
    if (trimmed) {
      /* 화면을 먼저 바꾸고 서버에 보낸다 — 이름 바꾸기는 되돌릴 수 있는 동작이라
         응답을 기다리며 입력칸을 붙잡아 둘 이유가 없다. 실패하면 서버 값으로
         되돌린다 — 바뀐 척 남겨두면 다음에 열었을 때 예전 이름이 돌아와 있어 더
         혼란스럽다. */
      setSchedules((prev) =>
        prev.map((item) => (item.id === id ? { ...item, label: trimmed } : item)),
      );
      void renameSavedSchedule(id, trimmed).catch(() => {
        void refreshSavedSchedules();
      });
    }
    /* 빈 제목은 취소로 친다. 서버도 빈 제목을 거부하므로 보내봐야 400이다. */
    setRenaming(null);
  }

  /*
   * 저장한 일정이 없으면 이 구획을 통째로 그리지 않는다.
   *
   * 예전에는 "아직 저장한 일정이 없어요"를 여기서 냈는데, 일정도 없고 저장한 것도
   * 없는 첫 화면에서 **비었다는 안내가 두 개 겹쳐 보였다**("아직 짠 일정이 없어요"
   * 아래에 이 문장이 또 붙었다). 비었을 때 무엇을 안내할지는 화면(SchedulePage)이
   * 정한다 — 거기만 "지금 일정"과 "저장한 일정"을 둘 다 알고 있다.
   */
  if (schedules.length === 0) return null;

  const markedDateKeys = new Set(
    schedules
      .map((entry) => entry.createdAt)
      .filter((createdAt): createdAt is Date => createdAt !== null)
      .map(toDateKey),
  );
  const visible = schedules.filter(
    (entry) => matchesQuery(entry.label, query) && matchesDate(entry.createdAt, selectedDateKey),
  );

  return (
    <section className="flex flex-col gap-3">
      <div className="flex h-11 items-center gap-2 rounded-xl border border-border bg-white px-3">
        <Search size={15} className="shrink-0 text-muted" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label={isEn ? "Search saved schedules" : "저장한 일정 검색"}
          placeholder={isEn ? "Search saved schedules" : "저장한 일정 이름으로 검색"}
          className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-muted"
        />
      </div>

      <ScheduleCalendarStrip
        weekStart={weekStart}
        onWeekChange={setWeekStart}
        selectedDateKey={selectedDateKey}
        onSelectDate={setSelectedDateKey}
        markedDateKeys={markedDateKeys}
        isEn={isEn}
      />

      {visible.length === 0 && (
        <p className="py-4 text-center text-[13px] text-muted">
          {isEn ? "No saved schedules match." : "조건에 맞는 저장한 일정이 없어요."}
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {visible.map((entry) => (
          <li key={entry.id} className="relative rounded-2xl border border-border p-3">
            {renaming === entry.id ? (
              <input
                ref={renameInputRef}
                aria-label={isEn ? "Schedule name" : "일정 이름"}
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
              <div className="flex items-center gap-3">
                {identity && <IdentityAvatar identity={identity} size="md" />}
                {/* 한 줄 전체가 버튼이다 — 날짜 쪽을 눌렀을 때 아무 일도 안 나면
                    고장으로 보인다. */}
                <button
                  type="button"
                  aria-label={isEn ? `Open schedule ${entry.label}` : `${entry.label} 일정 열기`}
                  /* 여기는 이미 /schedule 안이다 — 같은 경로를 새로 push 하면
                       뒤로가기가 한 번 더 필요해진다. 쿼리만 바꿔(replace) 같은
                       화면에서 갈아 끼운다. */
                  onClick={() =>
                    navigate(`/schedule?saved=${encodeURIComponent(entry.id)}`, {
                      replace: true,
                    })
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
                      /* 화면에서 먼저 빼고 서버에 보낸다. 실패하면 서버 목록으로
                           되돌린다. */
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
    </section>
  );
}
