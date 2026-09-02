/*
 * 역할: 회원가입 화면(DESIGN_SYSTEM.md §12.3 인증 화면 4종 중 하나).
 * 백엔드에 아직 회원가입 API가 없어(D-062 Phase 5) UI만 미리 자리 잡아 둔다 —
 * 제출해도 계정이 만들어지지 않고 ComingSoonNotice만 뜬다.
 */

import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AuthLayout, ComingSoonNotice } from "../auth/AuthLayout";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export function SignupPage() {
  const [agreed, setAgreed] = useState(false);
  const [showComingSoon, setShowComingSoon] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setShowComingSoon(true);
  }

  return (
    <AuthLayout
      title="회원가입"
      description="이메일로 계정을 만들면 어느 기기에서든 이용 기록이 이어져요."
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="signup-email">이메일</Label>
          <Input
            id="signup-email"
            type="email"
            placeholder="you@example.com"
            autoComplete="email"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="signup-password">비밀번호</Label>
          <Input
            id="signup-password"
            type="password"
            placeholder="8자 이상"
            autoComplete="new-password"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="signup-password-confirm">비밀번호 확인</Label>
          <Input
            id="signup-password-confirm"
            type="password"
            placeholder="비밀번호 다시 입력"
            autoComplete="new-password"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-ink">
          <Checkbox
            checked={agreed}
            onCheckedChange={(checked) => setAgreed(checked === true)}
            aria-label="이용약관 및 개인정보 처리방침에 동의"
          />
          이용약관 및 개인정보 처리방침에 동의해요
        </label>
        <Button type="submit" size="lg" disabled={!agreed}>
          가입하기
        </Button>
        {showComingSoon && <ComingSoonNotice />}
      </form>

      <p className="text-center text-xs text-muted">
        이미 계정이 있으신가요?{" "}
        <Link to="/login" className="font-semibold text-brand hover:underline">
          로그인
        </Link>
      </p>
    </AuthLayout>
  );
}
