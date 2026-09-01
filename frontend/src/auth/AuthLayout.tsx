/*
 * 역할: 인증 화면 4종(로그인·회원가입·아이디찾기·비밀번호찾기)이 공유하는 중앙 정렬 레이아웃.
 * 근거: DESIGN_SYSTEM.md §12.2 — 사이드바 없음, 모바일/데스크톱 모두 폭 제한된 단일 컬럼.
 */

import type { ReactNode } from "react";

interface AuthLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
}

export function AuthLayout({ title, description, children }: AuthLayoutProps) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-sm flex-col justify-center gap-6 px-6 py-10">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold text-ink">{title}</h1>
        {description && <p className="text-sm text-muted">{description}</p>}
      </div>
      {children}
    </main>
  );
}

/** 백엔드가 아직 없는 제출 동작 자리에 붙인다 — 눌러도 아무 일도 안 일어나는 이유를 알려준다. */
export function ComingSoonNotice() {
  return (
    <p role="status" className="rounded-xl bg-sky-light px-3.5 py-2.5 text-xs text-brand-deep">
      아직 준비 중인 기능이에요. 지금은 게스트로만 시작할 수 있어요.
    </p>
  );
}
