/*
 * 역할: 회원가입 화면에서 이용약관·개인정보처리방침을 보여주는 모달.
 * 입력: 없음.
 * 출력: onClose.
 * 호출 시점: SignupPage의 약관 줄 오른쪽 "보기" 버튼.
 * 근거: Figma "Modal — 이용약관"(64:2). 모달 본체는 64:39, 본문 묶음은 64:47,
 *   하단 버튼은 64:61("확인했어요"). package_D/DESIGN_SYSTEM.md §6.15와 같은 골격이다.
 *
 * **본문은 아직 비어 있다.** 목차만 세워 두고 각 조항 자리에 "준비 중"을 적는다.
 * Figma 시안에는 4개 조항의 문장이 채워져 있지만 그대로 옮기지 않았다 — 그 문장이
 * 지금 코드가 하는 일과 어긋나기 때문이다. 예를 들어 시안은 "수집된 정보는 추천
 * 정확도 개선 목적으로만 사용되며, 관련 법령에 따라 안전하게 보관됩니다"라고 적는데,
 * 실제로는 (1) GPS 좌표를 행정동이 아니라 원본으로 저장하고 (2) 대화 원문이 리전을
 * 지정할 수 없는 경로로 국외에 나가며 (3) 보관기간 자동 삭제가 수동 스크립트다.
 * **지키지 못하는 문장을 약관에 적는 것이 안 적는 것보다 나쁘다.**
 *
 * 초안과 확정 전에 해야 할 일은 package_D/[초안] 이용약관·개인정보처리방침.md에 있다.
 */

import { useEffect, useId } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

interface TermsModalProps {
  onClose: () => void;
}

/*
 * Figma 64:48~64:59의 조항 제목이다. 본문 없이 제목만 두는 이유는, 무엇이 들어올
 * 자리인지는 지금도 말할 수 있기 때문이다 — 빈 모달보다 낫고, 없는 내용을 지어내는
 * 것보다도 낫다.
 */
const SECTIONS = [
  "제1조 (목적)",
  "제2조 (서비스 이용)",
  "제3조 (개인정보 수집 및 이용)",
  "제4조 (이용자의 의무)",
] as const;

export function TermsModal({ onClose }: TermsModalProps) {
  const titleId = useId();

  /* 형제 모달(AddFavorite·AddKeyword)에는 없는 처리다. 저 둘은 입력칸 하나짜리라
     닫을 곳이 바로 보이지만, 이건 본문이 길어 스크롤하다 보면 X 버튼이 화면 밖으로
     밀린다 — 키보드로도 빠져나갈 길을 둔다. */
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 md:items-center">
      <button
        type="button"
        aria-label="닫기"
        onClick={onClose}
        className="absolute inset-0 bg-ink-strong/40"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative flex max-h-[80dvh] w-full max-w-md flex-col rounded-3xl bg-white p-5 pb-6 shadow-card"
      >
        {/* Head — Figma 64:40. 제목 왼쪽, 닫기 아이콘 오른쪽 끝. */}
        <div className="flex shrink-0 items-center justify-between gap-2">
          <h2 id={titleId} className="text-base font-bold text-ink">
            이용약관 및 개인정보처리방침
          </h2>
          <button
            type="button"
            aria-label="닫기"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center text-muted transition-colors hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        {/* 본문 — Figma 64:47. 길어지면 이 안에서만 스크롤한다. */}
        <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
          <p className="rounded-xl bg-sky-light px-3.5 py-2.5 text-xs leading-relaxed text-brand-deep">
            약관 전문은 아직 준비 중이에요. 아래 항목이 들어올 예정이에요.
          </p>

          <ul className="mt-4 flex flex-col gap-4">
            {SECTIONS.map((section) => (
              <li key={section}>
                <h3 className="text-sm font-bold text-ink">{section}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">준비 중이에요.</p>
              </li>
            ))}
          </ul>
        </div>

        {/* Figma 64:61은 "확인했어요"다. 동의 체크박스를 대신 켜지는 않는다 —
            읽었다는 것과 동의한다는 것은 다르고, 동의는 사용자가 직접 눌러야 한다. */}
        <button
          type="button"
          onClick={onClose}
          className="mt-5 flex h-12 w-full shrink-0 items-center justify-center rounded-full bg-brand text-sm font-bold text-white transition-colors hover:bg-brand-deep"
        >
          확인했어요
        </button>
      </div>
    </div>,
    document.body,
  );
}
