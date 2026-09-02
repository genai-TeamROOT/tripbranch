/*
 * 역할: 취향 설정 화면. Figma "Preferences"(28:2) 화면을 옮긴 것으로,
 *   사용자 단위 취향을 받아 줄 자리가 프론트·백엔드 어디에도 아직 없어
 *   선택은 이 화면 안에서만 기억되고 저장되지 않는다.
 * 호출 시점: 사이드바 "취향 설정"에서 전체 페이지로 연다(시트 아님 — §5.1의
 *   SHEET_PATH_PATTERNS에 /preferences가 없다).
 *
 * 칩 목록과 각 칩이 대응하는 DB 코드는 preferenceOptions.ts에 있다 —
 * 근거가 있는 문구만 남긴 목록이라 그 배경도 거기 적혀 있다.
 */

import { Compass, Plus, Sparkles, Users } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/layout/AppHeader";
import { AddKeywordModal } from "../components/layout/AddKeywordModal";
import {
  COMPANION_OPTIONS,
  MOOD_OPTIONS,
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
}: {
  icon: typeof Sparkles;
  label: string;
  options: readonly PreferenceOption[];
  selected: Set<string>;
  onToggle: (option: string) => void;
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
              {option.label}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function PreferencesPage() {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [customKeywords, setCustomKeywords] = useState<string[]>([]);
  const [showAddKeyword, setShowAddKeyword] = useState(false);
  const [showComingSoon, setShowComingSoon] = useState(false);

  function toggle(option: string) {
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

  function handleReset() {
    setSelected(new Set());
    setCustomKeywords([]);
  }

  function handleAddKeyword(keyword: string) {
    if (selected.size >= MAX_SELECTED || selected.has(keyword)) return;
    setCustomKeywords((prev) => (prev.includes(keyword) ? prev : [...prev, keyword]));
    setSelected((prev) => new Set(prev).add(keyword));
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
              어떤 순간에
              <br />
              끌리시나요?
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              선택한 취향은 상황별 추천에 반영돼요. 최소 {MIN_SELECTED}개, 최대 {MAX_SELECTED}개까지
              골라주세요.
            </p>

            {/* 부제와 Meta 사이만 12다(28:20) — 컨테이너 gap 24를 쓰면 두 배로 벌어진다. */}
            <div className="mt-3 flex items-center justify-between">
              <span className="rounded-full bg-chip px-3 py-1.5 text-xs font-bold text-brand-deep">
                {selected.size} / {MAX_SELECTED}개 선택됨
              </span>
              <button
                type="button"
                onClick={handleReset}
                disabled={selected.size === 0}
                className="text-xs font-bold text-muted transition-colors hover:text-ink disabled:opacity-40"
              >
                선택 초기화
              </button>
            </div>
          </div>

          <ChipGroup
            icon={Sparkles}
            label="분위기"
            options={MOOD_OPTIONS}
            selected={selected}
            onToggle={toggle}
          />
          <ChipGroup
            icon={Compass}
            label="테마"
            options={THEME_OPTIONS}
            selected={selected}
            onToggle={toggle}
          />
          <ChipGroup
            icon={Users}
            label="동행"
            options={COMPANION_OPTIONS}
            selected={selected}
            onToggle={toggle}
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
            <Plus size={16} /> 키워드 직접 입력
          </button>

          {showComingSoon && (
            <p
              role="status"
              className="rounded-xl bg-sky-light px-3.5 py-2.5 text-xs text-brand-deep"
            >
              아직 취향을 저장해 추천에 반영하는 기능은 준비 중이에요. 지금은 채팅으로 조건을
              말해주시면 그때그때 반영해드려요.
            </p>
          )}
        </div>

        <div className="sticky bottom-0 z-20 mx-auto w-full max-w-2xl bg-gradient-to-t from-bg via-bg to-bg/0 px-4 pb-7 pt-4">
          <button
            type="button"
            disabled={!canSave}
            onClick={() => setShowComingSoon(true)}
            className="flex h-[52px] w-full items-center justify-center rounded-full bg-brand text-base font-bold text-white transition-colors disabled:bg-brand/40"
          >
            {canSave ? "저장하기" : `${remaining}개 더 골라주세요`}
          </button>
        </div>
      </div>

      {showAddKeyword && (
        <AddKeywordModal onAdd={handleAddKeyword} onClose={() => setShowAddKeyword(false)} />
      )}
    </main>
  );
}
