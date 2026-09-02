/*
 * 역할: 아이디 찾기 화면(DESIGN_SYSTEM.md §12.3 인증 화면 4종 중 하나).
 * 백엔드에 아직 조회 API가 없어(D-062 Phase 5) UI만 미리 자리 잡아 둔다 —
 * 제출해도 조회되지 않고 ComingSoonNotice만 뜬다.
 */

import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AuthLayout, ComingSoonNotice } from "../auth/AuthLayout";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export function FindIdPage() {
  const [showComingSoon, setShowComingSoon] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setShowComingSoon(true);
  }

  return (
    <AuthLayout
      title="아이디 찾기"
      description="가입할 때 등록한 이름과 전화번호로 이메일을 찾아드려요."
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="find-id-name">이름</Label>
          <Input id="find-id-name" type="text" placeholder="이름" autoComplete="name" />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="find-id-phone">전화번호</Label>
          <Input id="find-id-phone" type="tel" placeholder="010-0000-0000" autoComplete="tel" />
        </div>
        <Button type="submit" size="lg">
          아이디 찾기
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
