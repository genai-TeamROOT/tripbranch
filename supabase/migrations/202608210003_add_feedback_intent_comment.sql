begin;

-- Package B (roadmap.md 14번 후속, D-068 연장): 피드백 분석 편의를 위한
-- 확장 필드 2개.
--
-- intent: 그 턴의 assistant_text 메시지가 이미 들고 있는 값(예: RECOMMEND/
-- INFO/COMPARE)을 그대로 복사해온다 — "어떤 인텐트가 싫어요를 많이
-- 받는지" 필터링용. B는 값을 검증하지 않고 호출자(프론트가 그대로 전달한
-- A의 분류 결과)를 그대로 저장한다.
--
-- comment: "싫어요" 사유를 사용자가 직접 남긴 자유 텍스트(선택). user_input/
-- assistant_message와 같은 이유로 nullable — 프론트가 안 보내면 rating
-- 기록 자체는 그대로 유효하다. 자유 텍스트라는 점에서 user_input/
-- assistant_message와 동일한 위험 등급으로 취급한다(guest-auth-design.md
-- 9절, 보관기간 정책 미정 — 개발/테스트 단계 전제는 동일).
alter table public.response_feedback
  add column if not exists intent text,
  add column if not exists comment text;

commit;
