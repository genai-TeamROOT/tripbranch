/*
 * 역할: 취향 설정 화면. Figma "Preferences"(28:2) 화면을 옮긴 것이다.
 *   저장하면 **계정에 남고**(PUT /api/preferences) 이 기기에도 함께 남는다
 *   (state/preferenceSync.ts). 홈 화면이 그 값을 다시 보여준다 — 확인하러 이
 *   화면까지 들어오지 않아도 되게.
 * 호출 시점: 사이드바 "취향 설정"에서 전체 페이지로 연다(시트 아님 — §5.1의
 *   SHEET_PATH_PATTERNS에 /preferences가 없다).
 *
 * **저장해도 추천 순위는 아직 달라지지 않는다.** 고른 값을 추천 요청에 싣는
 * 경로는 순위가 바뀌는 변경이라 실측한 뒤에 넣기로 했다. 그래서 부제도 Figma의
 * "상황별 추천에 반영돼요"를 그대로 쓰지 않았다 — 안 되는 일을 된다고 말하는
 * 문구가 된다.
 *
 * 칩 목록과 각 칩이 대응하는 DB 코드는 preferenceOptions.ts에 있다 —
 * 근거가 있는 문구만 남긴 목록이라 그 배경도 거기 적혀 있다.
 */

import { Compass, Plus, Sparkles, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorBanner } from "../components/ErrorBanner";
import { AppHeader } from "../components/layout/AppHeader";
import { AddKeywordModal } from "../components/layout/AddKeywordModal";
import { loadPreferences, type SavedPreference } from "../state/preferenceStorage";
import { pushPreferences, syncPreferences } from "../state/preferenceSync";
import { useTripState } from "../state/TripContext";
import {
  COMPANION_OPTIONS,
  MOOD_OPTIONS,
  PREFERENCE_GROUPS,
  THEME_OPTIONS,
  type PreferenceOption,
} from "./preferenceOptions";

const MIN_SELECTED = 3;
const MAX_SELECTED = 5;

function ChipGroup({
  icon: Icon,
  label,
  options,
  selected,
  onToggle,
  isEn,
}: {
  icon: typeof Sparkles;
  label: string;
  options: readonly PreferenceOption[];
  selected: Set<string>;
  onToggle: (option: string) => void;
  isEn: boolean;
}) {
  return (
    <section className="flex w-full flex-col gap-2.5">
      <div className="flex items-center gap-1.5">
        <Icon size={14} className="text-label" />
        <h2 className="text-xs font-bold text-label">{label}</h2>
      </div>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const isSelected = selected.has(option.label);
          return (
            <button
              key={option.label}
              type="button"
              aria-pressed={isSelected}
              onClick={() => onToggle(option.label)}
              className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                isSelected ? "bg-brand text-white" : "bg-white text-ink shadow-resting"
              }`}
            >
              {isEn ? option.labelEn : option.label}
            </button>
          );
        })}
      </div>
    </section>
  );
}

/** 라벨로 옵션을 되찾는다. 목록에 없으면 사용자가 직접 넣은 키워드다. */
function toSavedPreference(label: string): SavedPreference {
  const option = PREFERENCE_GROUPS.flat().find((candidate) => candidate.label === label);
  return option
    ? { label, source: option.source, codes: option.codes }
    : { label, source: "custom", codes: [] };
}

export function PreferencesPage() {
  const navigate = useNavigate();
  const { language } = useTripState();
  const isEn = language === "en";

  /* 저장해 둔 값이 있으면 그 상태로 열린다 — 다시 고르게 하지 않는다. */
  const [restored] = useState(loadPreferences);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(restored.map((preference) => preference.label)),
  );
  const [customKeywords, setCustomKeywords] = useState<string[]>(() =>
    restored.filter((preference) => preference.source === "custom").map(({ label }) => label),
  );
  const [showAddKeyword, setShowAddKeyword] = useState(false);
  const [cleared, setCleared] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  /* state가 아니라 ref다 — 아래 effect의 then 콜백이 마운트 시점의 값을 붙잡고
     있어서, state로 두면 사용자가 칩을 만져도 콜백은 계속 false로 본다. */
  const touchedRef = useRef(false);

  /*
   * 이 기기 값으로 먼저 그린 뒤 계정 값으로 맞춘다. 로딩 화면을 두지 않는 이유는
   * 대부분의 경우 둘이 같아서 깜빡임만 남기 때문이다. 다른 기기에서 바꾼 경우에만
   * 선택이 바뀌고, 그때는 바뀌는 것이 맞다.
   *
   * 사용자가 이미 칩을 만지기 시작했으면 덮어쓰지 않는다 — 서버 응답이 늦게 와서
   * 방금 고른 것을 지우면 안 된다.
   */
  useEffect(() => {
    let active = true;
    void syncPreferences().then((synced) => {
      if (!active || touchedRef.current) return;
      setSelected(new Set(synced.map((preference) => preference.label)));
      setCustomKeywords(
        synced.filter((preference) => preference.source === "custom").map(({ label }) => label),
      );
    });
    return () => {
      active = false;
    };
  }, []);

  function toggle(option: string) {
    touchedRef.current = true;
    setCleared(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(option)) {
        next.delete(option);
      } else if (next.size < MAX_SELECTED) {
        next.add(option);
      }
      return next;
    });
  }

  /*
   * 초기화는 저장해 둔 값까지 지운다. 화면만 비우면 저장값을 되돌릴 방법이
   * 없어서다 — 저장 버튼은 3개 미만이면 눌리지 않으므로 "다 빼고 저장"이라는
   * 경로가 존재하지 않는다.
   */
  async function handleReset() {
    touchedRef.current = true;
    setSelected(new Set());
    setCustomKeywords([]);
    const hadSaved = loadPreferences().length > 0;
    setErrorMessage(null);
    /* 계정에도 반영한다. 빈 목록을 저장하는 것이지 행을 지우는 게 아니다 —
       "아직 고른 적 없음"과 "다 지웠음"은 다른 상태다. */
    try {
      await pushPreferences([]);
      setCleared(hadSaved);
    } catch {
      /* 이 기기에서는 이미 지워졌다(pushPreferences가 로컬을 먼저 쓴다). */
      setCleared(hadSaved);
      setErrorMessage(
        isEn
          ? "Couldn't remove this from your account. It may still remain on other devices."
          : "계정에서 지우지 못했어요. 다른 기기에는 아직 남아 있을 수 있어요.",
      );
    }
  }

  function handleAddKeyword(keyword: string) {
    if (selected.size >= MAX_SELECTED || selected.has(keyword)) return;
    touchedRef.current = true;
    setCleared(false);
    setCustomKeywords((prev) => (prev.includes(keyword) ? prev : [...prev, keyword]));
    setSelected((prev) => new Set(prev).add(keyword));
  }

  /*
   * 저장하면 홈으로 보낸다. 저장했다는 안내를 이 화면에 띄우고 머무르게 하면
   * 결과를 보려고 사용자가 한 번 더 홈으로 이동해야 한다 — 그 왕복을 없애려고
   * 만든 기능이라 여기서 끝내면 앞뒤가 안 맞는다. 홈에 뜬 "내 취향" 줄 자체가
   * 저장됐다는 확인이다.
   */
  async function handleSave() {
    if (isSaving) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await pushPreferences([...selected].map(toSavedPreference));
      navigate("/");
    } catch {
      /* 고른 값은 이 기기에 이미 저장됐다. 다만 계정에 못 올렸으므로 다른
         기기에서는 안 보인다 — 그 사실을 알리고 화면에 머문다. */
      setErrorMessage(
        isEn
          ? "Couldn't save this to your account. It's still saved on this device."
          : "계정에 저장하지 못했어요. 이 기기에는 남아 있어요.",
      );
    } finally {
      setIsSaving(false);
    }
  }

  const remaining = MIN_SELECTED - selected.size;
  const canSave = remaining <= 0;

  return (
    <main className="relative flex h-full flex-col overflow-y-auto">
      {/*
       * 260px 띠가 위에서 옅게 시작해 30% 지점에서 가장 진하고 다시 사라진다.
       * 정점을 가운데(50%)에 두면 파란 기가 제목 아래까지 내려온다 — Figma 28:3의
       * 실제 픽셀을 재보면 정점이 위에서 70px, 즉 27% 지점이다.
       */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[260px] bg-gradient-to-b from-sky-light/0 via-sky-light via-30% to-sky-light/0"
      />
      <div className="relative z-10 flex flex-1 flex-col">
        <AppHeader onBack={() => navigate(-1)} />
        {/*
         * 세로 간격은 Figma Preferences(28:2)의 gap 프레임을 그대로 따른다 —
         * 헤더 아래 24(56:2), 묶음 사이 24, 마지막 요소와 BottomBar 사이 24(28:102).
         */}
        <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-4 pb-6 pt-6">
          <div>
            <h1 className="text-2xl font-bold leading-snug text-ink">
              {isEn ? (
                <>
                  What kind of moments
                  <br />
                  draw you in?
                </>
              ) : (
                <>
                  어떤 순간에
                  <br />
                  끌리시나요?
                </>
              )}
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              {isEn
                ? `You can see your picks again on the home screen. Applying them to recommendations is still in the works. Pick at least ${MIN_SELECTED} and up to ${MAX_SELECTED}.`
                : `고른 취향은 홈 화면에서 다시 볼 수 있어요. 추천 결과에 반영하는 건 아직 준비 중이에요. 최소 ${MIN_SELECTED}개, 최대 ${MAX_SELECTED}개까지 골라주세요.`}
            </p>

            {/* 부제와 Meta 사이만 12다(28:20) — 컨테이너 gap 24를 쓰면 두 배로 벌어진다. */}
            <div className="mt-3 flex items-center justify-between">
              <span className="rounded-full bg-chip px-3 py-1.5 text-xs font-bold text-brand-deep">
                {isEn ? `${selected.size} / ${MAX_SELECTED} selected` : `${selected.size} / ${MAX_SELECTED}개 선택됨`}
              </span>
              <button
                type="button"
                onClick={handleReset}
                disabled={selected.size === 0}
                className="text-xs font-bold text-muted transition-colors hover:text-ink disabled:opacity-40"
              >
                {isEn ? "Clear selection" : "선택 초기화"}
              </button>
            </div>
          </div>

          <ChipGroup
            icon={Sparkles}
            label={isEn ? "Mood" : "분위기"}
            options={MOOD_OPTIONS}
            selected={selected}
            onToggle={toggle}
            isEn={isEn}
          />
          <ChipGroup
            icon={Compass}
            label={isEn ? "Theme" : "테마"}
            options={THEME_OPTIONS}
            selected={selected}
            onToggle={toggle}
            isEn={isEn}
          />
          <ChipGroup
            icon={Users}
            label={isEn ? "Companions" : "동행"}
            options={COMPANION_OPTIONS}
            selected={selected}
            onToggle={toggle}
            isEn={isEn}
          />

          {customKeywords.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {customKeywords.map((keyword) => (
                <button
                  key={keyword}
                  type="button"
                  aria-pressed={selected.has(keyword)}
                  onClick={() => toggle(keyword)}
                  className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                    selected.has(keyword)
                      ? "bg-brand text-white"
                      : "bg-white text-ink shadow-resting"
                  }`}
                >
                  {keyword}
                </button>
              ))}
            </div>
          )}

          <button
            type="button"
            onClick={() => setShowAddKeyword(true)}
            className="flex items-center gap-1.5 self-start text-sm font-bold text-brand"
          >
            <Plus size={16} /> {isEn ? "Add your own keyword" : "키워드 직접 입력"}
          </button>

          {errorMessage && <ErrorBanner message={errorMessage} />}

          {cleared && (
            <p
              role="status"
              className="rounded-xl bg-chip px-3.5 py-2.5 text-xs leading-relaxed text-ink"
            >
              {isEn
                ? "Your saved preferences have been cleared. They'll also disappear from the home screen."
                : "저장해 둔 취향을 지웠어요. 홈 화면에서도 사라져요."}
            </p>
          )}
        </div>

        <div className="sticky bottom-0 z-20 mx-auto w-full max-w-2xl bg-gradient-to-t from-bg via-bg to-bg/0 px-4 pb-7 pt-4">
          <button
            type="button"
            disabled={!canSave || isSaving}
            onClick={handleSave}
            className="flex h-[52px] w-full items-center justify-center rounded-full bg-brand text-base font-bold text-white transition-colors disabled:bg-brand/40"
          >
            {isEn
              ? isSaving
                ? "Saving…"
                : canSave
                  ? "Save"
                  : `Pick ${remaining} more`
              : isSaving
                ? "저장하는 중이에요…"
                : canSave
                  ? "저장하기"
                  : `${remaining}개 더 골라주세요`}
          </button>
        </div>
      </div>

      {showAddKeyword && (
        <AddKeywordModal onAdd={handleAddKeyword} onClose={() => setShowAddKeyword(false)} />
      )}
    </main>
  );
}
