begin;

-- 운영 DB에는 이미 수동으로 추가된 곳이 있어, 새 환경과 기존 환경 모두에서
-- 재현되도록 IF NOT EXISTS로 최소 실행 문맥을 보장한다.
alter table public.response_feedback
  add column if not exists intent text;

alter table public.response_feedback
  add column if not exists user_input text;

alter table public.response_feedback
  add column if not exists assistant_message text;

-- 싫어요 개선 사유를 자유 문장과 분리해 집계한다. 기존 feedback 행은 NULL을 유지한다.
alter table public.response_feedback
  add column if not exists reason_code text;

alter table public.response_feedback
  add constraint response_feedback_reason_code_valid
  check (
    reason_code is null
    or reason_code in (
      'intent_mismatch',
      'clarification_unhelpful',
      'context_not_preserved',
      'location_misunderstood',
      'conditions_not_applied',
      'recommendation_not_suitable',
      'other'
    )
  );

-- 사유는 모든 싫어요에 필수, 자유 의견은 어느 사유에서나 선택적으로 남길 수 있다.
alter table public.response_feedback
  add constraint response_feedback_reason_comment_consistent
  check (
    (rating = 'like' and reason_code is null and comment is null)
    or (rating = 'dislike' and reason_code is not null)
    -- 배포 전 기존 "싫어요 + comment만" 기록은 그대로 읽을 수 있게 둔다.
    or (rating = 'dislike' and reason_code is null)
  );

create index response_feedback_dislike_reason_recorded_idx
  on public.response_feedback (reason_code, recorded_at desc)
  where rating = 'dislike';

create or replace view public.response_feedback_kst as
select
  id,
  session_id,
  run_id,
  rating,
  intent,
  user_input,
  assistant_message,
  reason_code,
  comment,
  recorded_at,
  recorded_at at time zone 'Asia/Seoul' as recorded_at_kst
from public.response_feedback;

commit;
