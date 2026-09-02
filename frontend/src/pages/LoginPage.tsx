/*
 * 역할: 서비스 진입 관문. 정식 로그인이 들어오기 전까지 게스트 신원만 발급한다.
 * 입력: 게스트 시작 버튼 클릭, 리다이렉트로 넘어온 원래 목적지.
 * 출력: 게스트 세션 발급 후 원래 목적지로 이동, 실패 시 오류 문구.
 * 호출 시점: 신원 없이 보호 라우트에 접근했거나 /login으로 직접 들어올 때 호출된다.
 *
 * 이메일·비밀번호 입력은 Figma의 Login 프레임(27:6)을 그대로 옮긴 것으로, 아직
 * 백엔드가 없어(D-062 Phase 5) 제출해도 동작하지 않는다 — ComingSoonNotice로 그
 * 사실을 밝힌다. 게스트 시작만 실제로 동작한다.
 *
 * Figma와 다른 세 곳(2026-09-02 사용자 결정):
 * - Figma 하단은 "Google로 계속하기"인데 여기서는 **게스트 시작**이다. Google OAuth와
 *   "자동 로그인" 체크박스는 백엔드가 필요해 이번 범위에서 뺐다. 게스트 시작은 지금
 *   **유일하게 동작하는 진입 경로**라, Figma에 없다고 지우면 아무도 앱에 못 들어온다.
 * - 게스트 안내 문단은 뺐다("덜 눈에 띄게"). 고지 내용은 회원가입 도입 시 약관 화면으로
 *   옮긴다(D-062 9-3절).
 * - **아이디 찾기 링크를 뺐다.** 회원가입이 이름·이메일·비밀번호만 받으므로 아이디가
 *   곧 이메일이고, 찾을 대상이 따로 없다. 화면도 함께 지웠다.
 */

import { useState, type FormEvent } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { AuthLayout, ComingSoonNotice } from "../auth/AuthLayout";
import { ErrorBanner } from "../components/ErrorBanner";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export function LoginPage() {
  const { session, status, error: authError, signInAsGuest } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showComingSoon, setShowComingSoon] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  /* RequireUser가 넘겨준 원래 목적지. 직접 들어온 경우엔 홈으로 보낸다. */
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "ready" && session) {
    return <Navigate to={from} replace />;
  }

  function handleLoginSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setShowComingSoon(true);
  }

  async function handleGuestStart() {
    if (isLoading) return;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      await signInAsGuest();
      navigate(from, { replace: true });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "게스트로 시작하지 못했어요.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <AuthLayout
      title="TripBranch"
      description="로그인하고 지금 상황에 맞는 장소를 찾아보세요"
      footer={
        <>
          {/* 폼 밖에 있으므로 form 속성으로 연결한다 — Figma에서 버튼이 하단 바에 있다. */}
          <Button type="submit" form="login-form" size="lg">
            로그인
          </Button>

          <div className="flex items-center gap-3 text-xs text-muted">
            <span className="h-px flex-1 bg-border" />
            또는
            <span className="h-px flex-1 bg-border" />
          </div>

          <Button
            type="button"
            variant="outline"
            size="lg"
            disabled={isLoading || status !== "ready"}
            onClick={() => void handleGuestStart()}
          >
            {isLoading ? "시작하는 중이에요…" : "게스트로 시작하기"}
          </Button>
        </>
      }
    >
      {/* Figma는 Brand와 이 묶음 사이가 32, 묶음 안 요소 사이가 20이다. */}
      <div className="flex flex-col gap-5">
        {status === "unconfigured" ? (
          <section className="rounded-xl bg-chip p-3 text-sm text-ink">
            <p className="font-bold">인증 설정이 없어요</p>
            <p className="mt-1 text-muted">{authError}</p>
            <p className="mt-1 text-muted">frontend/.env를 채우고 개발 서버를 다시 시작해주세요.</p>
          </section>
        ) : null}

        {errorMessage ? <ErrorBanner message={errorMessage} /> : null}

        <form id="login-form" onSubmit={handleLoginSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="login-email">이메일</Label>
            <Input
              id="login-email"
              type="email"
              placeholder="example@email.com"
              autoComplete="email"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="login-password">비밀번호</Label>
            {/*
             * 눈 아이콘을 입력칸 안 오른쪽에 겹친다(Figma 27:33). 입력칸 자체에
             * 오른쪽 여백을 줘서 긴 값이 아이콘 밑으로 들어가지 않게 한다.
             */}
            <div className="relative">
              <Input
                id="login-password"
                type={showPassword ? "text" : "password"}
                placeholder="비밀번호를 입력하세요"
                autoComplete="current-password"
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

          {showComingSoon && <ComingSoonNotice />}
        </form>

        <div className="flex justify-center gap-3 text-xs text-muted">
          <Link to="/reset-password" className="hover:text-brand">
            비밀번호 찾기
          </Link>
          <span aria-hidden="true">·</span>
          <Link to="/signup" className="hover:text-brand">
            회원가입
          </Link>
        </div>
      </div>
    </AuthLayout>
  );
}
