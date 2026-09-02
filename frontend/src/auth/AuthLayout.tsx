/*
 * 역할: 인증 화면 4종(로그인·회원가입·아이디찾기·비밀번호찾기)이 공유하는 중앙 정렬 레이아웃.
 * 근거: DESIGN_SYSTEM.md §12.2 — 사이드바 없음, 모바일/데스크톱 모두 폭 제한된 단일 컬럼.
 *   Figma 인증 프레임 4개(Login 27:6 등)가 모두 같은 골격이다 — 위쪽 Body와
 *   화면 하단에 붙는 BottomBar.
 *
 * footer를 넘기면 그 골격으로 그린다(본문은 위, 동작 버튼은 하단 고정). 안 넘기면
 * 종전처럼 세로 가운데 정렬이다 — 화면을 하나씩 Figma에 맞추는 중이라, 아직 안 옮긴
 * 화면이 어정쩡하게 보이지 않도록 남겨 둔 전환용 분기다. 넷 다 옮기고 나면 지운다.
 */

import type { ReactNode } from "react";

interface AuthLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
  /** 화면 하단에 붙일 동작 영역(주 버튼·구분선 등). Figma의 BottomBar. */
  footer?: ReactNode;
}

export function AuthLayout({ title, description, children, footer }: AuthLayoutProps) {
  if (!footer) {
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

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-sm flex-col px-4">
      {/* Body — 위에서부터 쌓는다(Figma: Column y=64, Brand와 본문 사이 32). */}
      <div className="flex flex-1 flex-col gap-8 pt-16">
        <div className="flex flex-col gap-2 text-center">
          <h1 className="text-2xl font-bold text-brand">{title}</h1>
          {description && <p className="text-sm text-muted">{description}</p>}
        </div>
        {children}
      </div>

      {/* BottomBar — 화면 하단 고정. 본문이 길어지면 자연스럽게 아래로 밀린다. */}
      <div className="flex flex-col gap-3 pb-6 pt-4">{footer}</div>
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
