/*
 * 역할: 사이드바 즐겨찾기에 새 장소 라벨을 입력받는 모달.
 * 입력: 없음(내부 폼 상태).
 * 출력: onAdd(라벨) 또는 onClose.
 * 호출 시점: SideDrawerContent의 "즐겨찾기 + 추가" 버튼.
 * 근거: package_D/DESIGN_SYSTEM.md §6.15(모달 — 바텀시트형).
 */

import { useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

interface AddFavoriteModalProps {
  onAdd: (label: string) => void;
  onClose: () => void;
}

export function AddFavoriteModal({ onAdd, onClose }: AddFavoriteModalProps) {
  const [label, setLabel] = useState("");

  function handleSubmit() {
    const trimmed = label.trim();
    if (!trimmed) return;
    onAdd(trimmed);
    onClose();
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 md:items-center">
      <button
        type="button"
        aria-label="닫기"
        onClick={onClose}
        className="absolute inset-0 bg-ink-strong/40"
      />
      <div className="relative w-full max-w-md rounded-3xl bg-white p-5 pb-6 shadow-card">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-bold text-ink">즐겨찾기 추가</h2>
          <button
            type="button"
            aria-label="닫기"
            onClick={onClose}
            className="text-muted transition-colors hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>
        <input
          autoFocus
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") handleSubmit();
          }}
          placeholder="예: 회사 (역삼동)"
          className="w-full rounded-xl border border-border px-3.5 py-3 text-base text-ink outline-none focus:border-brand"
        />
        <button
          type="button"
          disabled={!label.trim()}
          onClick={handleSubmit}
          className="mt-4 flex h-12 w-full items-center justify-center rounded-full bg-brand text-sm font-bold text-white transition-colors hover:enabled:bg-brand-deep disabled:opacity-40"
        >
          추가
        </button>
      </div>
    </div>,
    document.body,
  );
}
