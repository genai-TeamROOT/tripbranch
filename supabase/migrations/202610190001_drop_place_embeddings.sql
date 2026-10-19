begin;

-- 취향 근거 벡터를 Pinecone으로 옮겼다(Supabase 무료 플랜 전환, 2026-10 팀 합의).
-- 내보내기 #453, 런타임 검색 #454, 새 임베딩 적재 #455가 머지되어 앱 코드·스크립트
-- 어디에서도 이 테이블과 search_place_evidence를 부르지 않는다.
-- Pinecone 레코드에 담기지 않는 열은 삭제 전에 따로 백업했다(2026-10-19).
--
-- search_place_evidence는 plpgsql이라 테이블과 의존 관계가 기록되지 않는다 —
-- 테이블만 지우면 함수가 남아 호출 시점에야 실패하므로 먼저 명시적으로 지운다.
-- cascade는 쓰지 않는다. 예상 밖 의존 객체가 있으면 조용히 함께 지우지 않고
-- 마이그레이션이 실패해서 드러나게 한다.
drop function if exists public.search_place_evidence(vector, text[], int, float);

drop table if exists public.place_embeddings;

commit;
