/*
 * 역할: 취향 설정 화면. Figma "Preferences"(28:2) 화면 그대로 옮긴 것으로,
 *   사용자 단위 취향 설정이라는 개념이 프론트·백엔드 어디에도 아직 없어(추천
 *   카드의 "장소별 방문자 취향 태그"는 리뷰에서 뽑은 장소 쪽 태그라 이것과
 *   다르다) 선택 자체는 이 화면 안에서만 기억되고 저장되지 않는다.
 * 호출 시점: 사이드바 "취향 설정"에서 전체 페이지로 연다(시트 아님 — §5.1의
 *   SHEET_PATH_PATTERNS에 /preferences가 없다).
 */

import { Compass, Plus, Sparkles, Users } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/layout/AppHeader";
import { AddKeywordModal } from "../components/layout/AddKeywordModal";

const MIN_SELECTED = 3;
const MAX_SELECTED = 5;

const MOOD_OPTIONS = [
  "조용한 곳",
  "아늑한 공간",
  "야경 명소",
  "사진 명소",
  "감성 인테리어",
  "한적한 골목",
  "뷰 맛집",
  "힙한 분위기",
];

const THEME_OPTIONS = [
  "자연·공원",
  "카페",
  "전시·문화",
  "로컬 맛집",
  "실내 활동",
  "액티비티",
  "서점·문구",
  "마켓·소품샵",
  "브런치",
  "디저트 맛집",
  "전통·역사",
  "루프탑",
];

const COMPANION_OPTIONS = [
  "아이와 함께",
  "반려동물 동반",
  "혼자 가기 좋은",
  "데이트 코스",
  "친구와 함께",
  "단체 모임",
];

function ChipGroup({
  icon: Icon,
  label,
  options,
  selected,
  onToggle,
}: {
  icon: typeof Sparkles;
  label: string;
  options: string[];
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
          const isSelected = selected.has(option);
          return (
            <button
              key={option}
              type="button"
              aria-pressed={isSelected}
              onClick={() => onToggle(option)}
              className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                isSelected ? "bg-brand text-white" : "bg-white text-ink shadow-resting"
              }`}
            >
              {option}
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
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[260px] bg-gradient-to-b from-sky-light/0 via-sky-light to-sky-light/0"
      />
      <div className="relative z-10 flex flex-1 flex-col">
        <AppHeader onBack={() => navigate(-1)} />
        <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-4 pb-32">
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
          </div>

          <div className="flex items-center justify-between">
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
