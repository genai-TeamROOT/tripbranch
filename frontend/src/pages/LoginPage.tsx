/*
 * 역할: 서비스 진입 관문. 정식 로그인이 들어오기 전까지 게스트 신원만 발급한다.
 * 입력: 게스트 시작 버튼 클릭, 리다이렉트로 넘어온 원래 목적지.
 * 출력: 게스트 세션 발급 후 원래 목적지로 이동, 실패 시 오류 문구.
 * 호출 시점: 신원 없이 보호 라우트에 접근했거나 /login으로 직접 들어올 때 호출된다.
 *
 * 이메일·비밀번호 입력은 DESIGN_SYSTEM.md §12.3의 인증 화면 구성을 미리 자리
 * 잡아 둔 것으로, 아직 백엔드가 없어(D-062 Phase 5) 제출해도 동작하지 않는다
 * — ComingSoonNotice로 그 사실을 밝힌다. 게스트 시작만 실제로 동작한다.
 */

import { useState, type FormEvent } from "react";
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
      description="지금 상황에 맞는 장소를 찾아드려요. 가입 없이 바로 시작할 수 있어요."
    >
      {status === "unconfigured" ? (
        <section className="rounded-xl bg-chip p-3 text-sm text-ink">
          <p className="font-bold">인증 설정이 없어요</p>
          <p className="mt-1 text-muted">{authError}</p>
          <p className="mt-1 text-muted">frontend/.env를 채우고 개발 서버를 다시 시작해주세요.</p>
        </section>
      ) : null}

      {errorMessage ? <ErrorBanner message={errorMessage} /> : null}

      <form onSubmit={handleLoginSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="login-email">이메일</Label>
          <Input id="login-email" type="email" placeholder="you@example.com" autoComplete="email" />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="login-password">비밀번호</Label>
          <Input
            id="login-password"
            type="password"
            placeholder="비밀번호"
            autoComplete="current-password"
          />
        </div>
        <Button type="submit" size="lg">
          로그인
        </Button>
        {showComingSoon && <ComingSoonNotice />}
      </form>

      <div className="flex justify-center gap-3 text-xs text-muted">
        <Link to="/signup" className="hover:text-brand">
          회원가입
        </Link>
        <span aria-hidden="true">·</span>
        <Link to="/find-id" className="hover:text-brand">
          아이디 찾기
        </Link>
        <span aria-hidden="true">·</span>
        <Link to="/reset-password" className="hover:text-brand">
          비밀번호 찾기
        </Link>
      </div>

      <div className="flex items-center gap-3 text-xs text-muted">
        <span className="h-px flex-1 bg-border" />
        또는
        <span className="h-px flex-1 bg-border" />
      </div>

      {/* 게스트로 시작해도 이용 기록이 남고, 나중에 계정을 연결하면 그 기록이 그대로
          이어진다(D-062 8절). 정식 로그인 도입 시 이 고지 자리를 수집 항목·목적·
          보관기간 안내로 확장한다(9-3절). */}
      <section className="rounded-xl bg-chip p-3 text-sm text-ink">
        게스트로 시작하면 대화 조건과 추천 이력이 이 기기에 연결돼요. 나중에 계정을 만들면
        지금까지의 기록을 그대로 이어서 쓸 수 있어요.
      </section>

      <Button
        type="button"
        variant="outline"
        size="lg"
        disabled={isLoading || status !== "ready"}
        onClick={() => void handleGuestStart()}
      >
        {isLoading ? "시작하는 중이에요…" : "게스트로 시작하기"}
      </Button>
    </AuthLayout>
  );
}
