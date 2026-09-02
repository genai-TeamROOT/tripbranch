/*
 * 역할: 회원가입 화면. Figma의 Signup 프레임(27:52)을 옮긴 것이다.
 * 백엔드에 아직 회원가입 API가 없어(D-062 Phase 5) UI만 미리 자리 잡아 둔다 —
 * 제출해도 계정이 만들어지지 않고 ComingSoonNotice만 뜬다.
 *
 * 약관 "보기"는 아직 갈 곳이 없다. Figma에는 링크로 있지만 약관 화면 자체가
 * 없어서(D-062 9-3절) 눌러도 준비 중 안내만 띄운다 — 죽은 링크를 만들지 않는다.
 */

import { useState, type FormEvent } from "react";
import { Eye, EyeOff } from "lucide-react";
import { AuthLayout, ComingSoonNotice } from "../auth/AuthLayout";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export function SignupPage() {
  const [agreed, setAgreed] = useState(false);
  const [showComingSoon, setShowComingSoon] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setShowComingSoon(true);
  }

  return (
    <AuthLayout
      title="회원가입"
      backTo="/login"
      footer={
        <Button type="submit" form="signup-form" size="lg" disabled={!agreed}>
          가입하고 시작하기
        </Button>
      }
    >
      <form id="signup-form" onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="signup-name">이름</Label>
          <Input
            id="signup-name"
            placeholder="이름을 입력하세요"
            autoComplete="name"
            aria-describedby="signup-name-help"
          />
          {/*
           * 이름을 왜 받는지 그 자리에서 밝힌다. 인증에 쓰이는 값이 아니라
           * 대화에서 부르는 호칭이라, 묻는 이유를 적어 두지 않으면 굳이 왜
           * 필요한지 알 수 없다. aria-describedby로 묶어 스크린 리더도 입력칸을
           * 읽을 때 함께 듣는다.
           */}
          <p id="signup-name-help" className="text-xs leading-relaxed text-muted">
            AI가 추천할 때 이 이름으로 불러드려요.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="signup-email">이메일</Label>
          <Input
            id="signup-email"
            type="email"
            placeholder="example@email.com"
            autoComplete="email"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="signup-password">비밀번호</Label>
          {/* 눈 아이콘은 로그인 화면과 같은 방식이다(Figma 27:72). */}
          <div className="relative">
            <Input
              id="signup-password"
              type={showPassword ? "text" : "password"}
              placeholder="8자 이상 입력하세요"
              autoComplete="new-password"
              className="pr-11"
            />
            <button
              type="button"
              onClick={() => setShowPassword((shown) => !shown)}
              aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}
              aria-pressed={showPassword}
              className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-muted transition-colors hover:text-ink"
            >
              {showPassword ? <EyeOff size={17} aria-hidden /> : <Eye size={17} aria-hidden />}
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="signup-password-confirm">비밀번호 확인</Label>
          <Input
            id="signup-password-confirm"
            type="password"
            placeholder="비밀번호를 한 번 더 입력하세요"
            autoComplete="new-password"
          />
        </div>

        {/* Figma 27:83 — 체크박스와 문구는 왼쪽, "보기"는 오른쪽 끝에 붙는다. */}
        <div className="flex items-center gap-2 text-sm text-ink">
          <Checkbox
            id="signup-agree"
            checked={agreed}
            onCheckedChange={(checked) => setAgreed(checked === true)}
          />
          <Label htmlFor="signup-agree" className="flex-1 font-normal">
            이용약관 및 개인정보처리방침에 동의합니다
          </Label>
          <button
            type="button"
            onClick={() => setShowComingSoon(true)}
            className="shrink-0 text-xs text-muted transition-colors hover:text-brand"
          >
            보기
          </button>
        </div>

        {showComingSoon && <ComingSoonNotice />}
      </form>
    </AuthLayout>
  );
}
