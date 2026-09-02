/*
 * 역할: 아이디 찾기 화면. Figma의 FindId 프레임(27:87)을 옮긴 것이다.
 * 백엔드에 아직 조회 API가 없어(D-062 Phase 5) UI만 미리 자리 잡아 둔다 —
 * 제출해도 조회되지 않는다.
 *
 * Figma의 결과 박스(27:104)는 "가입하신 아이디는 tr****@email.com 입니다."라는
 * 예시 문구를 보여주는데, 그 문자열을 그대로 화면에 두지는 않았다. 조회한 적이
 * 없는데 마치 결과인 것처럼 보이는 값이라 지어낸 정보가 된다. 박스의 생김새는
 * 그대로 두고 내용만 "아직 조회할 수 없다"는 사실로 채운다.
 */

import { useState, type FormEvent } from "react";
import { CircleCheck } from "lucide-react";
import { AuthLayout } from "../auth/AuthLayout";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export function FindIdPage() {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
  }

  return (
    <AuthLayout
      title="아이디 찾기"
      description="가입할 때 등록한 이메일을 입력하면 아이디를 확인해 드려요."
      backTo="/login"
      footer={
        <Button type="submit" form="find-id-form" size="lg">
          아이디 찾기
        </Button>
      }
    >
      <form id="find-id-form" onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="find-id-email">이메일</Label>
          <Input
            id="find-id-email"
            type="email"
            placeholder="example@email.com"
            autoComplete="email"
          />
        </div>

        {/* 결과 박스 자리(Figma 27:104). 지금은 조회가 안 되므로 그 사실을 적는다. */}
        {submitted && (
          <p
            role="status"
            className="flex items-start gap-2.5 rounded-xl bg-sky-light p-4 text-sm text-brand-deep"
          >
            <CircleCheck size={18} className="mt-0.5 shrink-0" aria-hidden />
            아직 준비 중인 기능이에요. 지금은 게스트로만 시작할 수 있어요.
          </p>
        )}
      </form>
    </AuthLayout>
  );
}
