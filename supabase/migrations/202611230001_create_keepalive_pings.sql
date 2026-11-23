-- 무료 플랜은 DB에 질의가 7일 동안 없으면 프로젝트를 정지한다. 2026-11-23에 정지
-- 예정 경고 메일이 왔는데, 그때까지 세션 정리(.github/workflows/cleanup-sessions.yml)가
-- 매일 성공하고 있었다. 다만 2026-11-17부터 지울 세션이 없어 select만 나갔다 --
-- **조회는 활동으로 집계되지 않는다.** 10월에는 매일 지울 세션이 있어 삭제가 함께
-- 일어났고, 그래서 그때까지 경고가 오지 않았다.
--
-- 이 표는 그 쓰기를 만들기 위한 것이고 다른 용도가 없다. 행은 하나만 두고
-- (id = 'default') 매일 pinged_at을 갱신한다. 값을 읽는 코드는 없다 -- 쓰기
-- 자체가 목적이다.
--
-- 서비스에 트래픽이 생겨 세션이 매일 쌓이면 이 표는 필요 없어진다. 그때는
-- 워크플로와 함께 지운다.
create table if not exists public.keepalive_pings (
  id text primary key,
  pinged_at timestamptz not null default now(),
  -- 어느 경로가 찔렀는지. 워크플로 실행 기록과 맞춰볼 때 쓴다.
  source text
);

-- 백엔드의 Secret Key로만 쓴다. anon/authenticated 클라이언트에는 정책을 두지
-- 않아 직접 접근을 기본 차단한다(public_toilets와 같은 방식).
alter table public.keepalive_pings enable row level security;
