/*
 * 역할: 비밀번호 찾기 화면. Figma의 ResetPassword 프레임(27:109)을 옮긴 것이다.
 * 백엔드에 아직 재설정 메일 발송이 없어(D-062 Phase 5) UI만 미리 자리 잡아 둔다 —
 * 눌러도 메일은 가지 않는다.
 *
 * Figma의 결과 박스(27:126)는 "example@email.com로 재설정 링크를 보냈어요"라고
 * 적혀 있는데, 실제로 보내지 않으므로 그 문구를 그대로 두지 않았다. 보낸 적이 없는데
 * 보냈다고 말하는 화면이 된다. 박스 생김새는 그대로 두고 내용만 사실로 채운다.
 */

import { useState, type FormEvent } from "react";
import { Mail } from "lucide-react";
import { AuthLayout } from "../auth/AuthLayout";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export function ResetPasswordPage() {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
  }

  return (
    <AuthLayout
      title="비밀번호 찾기"
      description="가입한 이메일로 비밀번호 재설정 링크를 보내드려요."
      backTo="/login"
      footer={
        <Button type="submit" form="reset-password-form" size="lg">
          재설정 링크 보내기
        </Button>
      }
    >
      <form id="reset-password-form" onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="reset-password-email">이메일</Label>
          <Input
            id="reset-password-email"
            type="email"
            placeholder="example@email.com"
            autoComplete="email"
          />
        </div>

        {/* 결과 박스 자리(Figma 27:126). 지금은 메일이 나가지 않으므로 그 사실을 적는다. */}
        {submitted && (
          <p
            role="status"
            className="flex items-start gap-2.5 rounded-xl bg-sky-light p-4 text-sm text-brand-deep"
          >
            <Mail size={18} className="mt-0.5 shrink-0" aria-hidden />
            아직 준비 중인 기능이에요. 지금은 게스트로만 시작할 수 있어요.
          </p>
        )}
      </form>
    </AuthLayout>
  );
}
