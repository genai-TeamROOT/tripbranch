/*
 * 역할: 비밀번호 찾기(재설정) 화면(DESIGN_SYSTEM.md §12.3 인증 화면 4종 중 하나).
 * 백엔드에 아직 재설정 메일 발송 API가 없어(D-062 Phase 5) UI만 미리 자리 잡아
 * 둔다 — 제출해도 메일이 가지 않고 ComingSoonNotice만 뜬다.
 */

import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AuthLayout, ComingSoonNotice } from "../auth/AuthLayout";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export function ResetPasswordPage() {
  const [showComingSoon, setShowComingSoon] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setShowComingSoon(true);
  }

  return (
    <AuthLayout
      title="비밀번호 찾기"
      description="가입한 이메일로 비밀번호 재설정 링크를 보내드려요."
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="reset-password-email">이메일</Label>
          <Input
            id="reset-password-email"
            type="email"
            placeholder="you@example.com"
            autoComplete="email"
          />
        </div>
        <Button type="submit" size="lg">
          재설정 링크 보내기
        </Button>
        {showComingSoon && <ComingSoonNotice />}
      </form>

      <p className="text-center text-xs text-muted">
        <Link to="/login" className="font-semibold text-brand hover:underline">
          로그인으로 돌아가기
        </Link>
      </p>
    </AuthLayout>
  );
}
