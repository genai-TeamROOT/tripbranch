/*
 * 역할: 현재 신원(게스트/정식 계정)을 사람이 읽을 라벨로 바꾼다.
 * 입력: Supabase session.
 * 출력: "게스트로 이용 중" 또는 계정 식별자(이메일 등).
 * 호출 시점: AuthStatusBadge(헤더/개발자 화면 배지)와 SideDrawerContent(사이드바
 *   라벨)가 같은 판정 로직을 공유한다 — 계정 표시 후보 순서가 어긋나면 두 곳의
 *   표시가 갈린다.
 */

import type { Session } from "@supabase/supabase-js";

/* is_anonymous는 Supabase가 익명 사용자에게 붙이는 표식이다. 계정을 연결하면
   같은 uid를 유지한 채 false가 되므로(D-062 2절), 이 분기만으로 승격 후 표시가
   자동으로 바뀐다. */
export function isGuestSession(session: Session): boolean {
  return session.user?.is_anonymous === true;
}

/* 계정 표시에 쓸 값. provider마다 채워주는 필드가 달라서 후보를 순서대로 본다 —
   이메일 로그인은 email, 카카오·구글은 user_metadata의 이름 계열만 오는 경우가 있고
   전화번호 로그인은 phone만 온다. 전부 비면 신원이 있다는 사실만 알린다. */
function accountLabel(session: Session): string {
  const metadata = (session.user?.user_metadata ?? {}) as Record<string, unknown>;
  const candidates = [
    session.user?.email,
    metadata.name,
    metadata.nickname,
    metadata.preferred_username,
    session.user?.phone,
  ];
  const label = candidates.find((value) => typeof value === "string" && value.trim().length > 0);
  return (label as string | undefined) ?? "로그인됨";
}

export function identityLabel(session: Session): string {
  return isGuestSession(session) ? "게스트로 이용 중" : accountLabel(session);
}
