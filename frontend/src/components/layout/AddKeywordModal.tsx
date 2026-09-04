/*
 * 역할: 취향 설정 화면에서 목록에 없는 키워드를 직접 입력받는 모달.
 * 입력: 없음(내부 폼 상태).
 * 출력: onAdd(키워드) 또는 onClose.
 * 호출 시점: PreferencesPage의 "키워드 직접 입력" 버튼.
 * 근거: Figma "Preferences"(28:2) — AddFavoriteModal(§6.15)과 같은 패턴.
 */

import { useId, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useTripState } from "../../state/TripContext";

interface AddKeywordModalProps {
  onAdd: (keyword: string) => void;
  onClose: () => void;
}

export function AddKeywordModal({ onAdd, onClose }: AddKeywordModalProps) {
  const [keyword, setKeyword] = useState("");
  const titleId = useId();
  const isEn = useTripState().language === "en";

  function handleSubmit() {
    const trimmed = keyword.trim();
    if (!trimmed) return;
    onAdd(trimmed);
    onClose();
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 md:items-center">
      <button
        type="button"
        aria-label={isEn ? "Close" : "닫기"}
        onClick={onClose}
        className="absolute inset-0 bg-ink-strong/40"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full max-w-md rounded-3xl bg-white p-5 pb-6 shadow-card"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 id={titleId} className="text-base font-bold text-ink">
            {isEn ? "Add your own keyword" : "키워드 직접 입력"}
          </h2>
          <button
            type="button"
            aria-label={isEn ? "Close" : "닫기"}
            onClick={onClose}
            className="text-muted transition-colors hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>
        <input
          autoFocus
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") handleSubmit();
          }}
          placeholder={isEn ? "e.g. quiet bookstore" : "예: 조용한 서점"}
          className="w-full rounded-xl border border-border px-3.5 py-3 text-base text-ink outline-none focus:border-brand"
        />
        <button
          type="button"
          disabled={!keyword.trim()}
          onClick={handleSubmit}
          className="mt-4 flex h-12 w-full items-center justify-center rounded-full bg-brand text-sm font-bold text-white transition-colors hover:enabled:bg-brand-deep disabled:opacity-40"
        >
          {isEn ? "Add" : "추가"}
        </button>
      </div>
    </div>,
    document.body,
  );
}
