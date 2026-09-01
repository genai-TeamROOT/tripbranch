/*
 * 역할: 취향 설정 화면. DESIGN_SYSTEM.md §12.3에 있는 화면이지만, 사용자 단위
 *   취향 설정이라는 개념이 프론트·백엔드 어디에도 아직 없어(추천 카드의
 *   "장소별 방문자 취향 태그"는 리뷰에서 뽑은 장소 쪽 태그라 이것과 다르다)
 *   UI만 먼저 자리 잡아 둔다. 선택은 이 화면 안에서만 기억되고 저장되지 않는다.
 * 호출 시점: 사이드바 "취향 설정"에서 전체 페이지로 연다(시트 아님 — §5.1의
 *   SHEET_PATH_PATTERNS에 /preferences가 없다).
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/layout/AppHeader";

const COMPANION_OPTIONS = ["혼자", "연인과", "친구와", "가족과"];
const BUDGET_OPTIONS = ["상관없어요", "가성비", "여유있게"];
const INTEREST_OPTIONS = ["카페", "맛집", "전시·박물관", "자연·산책", "사진 명소", "야경"];

function ChipGroup({
  options,
  selected,
  onToggle,
}: {
  options: string[];
  selected: string[];
  onToggle: (option: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group">
      {options.map((option) => {
        const isSelected = selected.includes(option);
        return (
          <button
            key={option}
            type="button"
            aria-pressed={isSelected}
            onClick={() => onToggle(option)}
            className={`rounded-full px-3.5 py-2 text-sm font-medium transition-colors ${
              isSelected ? "bg-brand text-white" : "bg-chip text-ink hover:bg-sky-light"
            }`}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}

export function PreferencesPage() {
  const navigate = useNavigate();
  const [companion, setCompanion] = useState<string[]>([]);
  const [budget, setBudget] = useState<string[]>([]);
  const [interests, setInterests] = useState<string[]>([]);
  const [showComingSoon, setShowComingSoon] = useState(false);

  function toggleSingle(value: string, current: string[], setValue: (next: string[]) => void) {
    setValue(current.includes(value) ? [] : [value]);
  }

  function toggleMultiple(value: string, current: string[], setValue: (next: string[]) => void) {
    setValue(
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    );
  }

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader onBack={() => navigate(-1)} />
      <div className="flex flex-1 flex-col gap-6 px-4 pb-10">
        <h1 className="text-[24px] font-bold leading-snug text-ink">취향 설정</h1>

        <section className="flex flex-col gap-2">
          <h2 className="text-xs font-bold text-label">누구와 자주 다니나요</h2>
          <ChipGroup
            options={COMPANION_OPTIONS}
            selected={companion}
            onToggle={(value) => toggleSingle(value, companion, setCompanion)}
          />
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-xs font-bold text-label">예산</h2>
          <ChipGroup
            options={BUDGET_OPTIONS}
            selected={budget}
            onToggle={(value) => toggleSingle(value, budget, setBudget)}
          />
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-xs font-bold text-label">관심사(여러 개 선택 가능)</h2>
          <ChipGroup
            options={INTEREST_OPTIONS}
            selected={interests}
            onToggle={(value) => toggleMultiple(value, interests, setInterests)}
          />
        </section>

        <button
          type="button"
          onClick={() => setShowComingSoon(true)}
          className="rounded-full bg-brand py-3 text-sm font-semibold text-white transition hover:bg-brand-deep active:scale-[0.98]"
        >
          저장하기
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
    </main>
  );
}
