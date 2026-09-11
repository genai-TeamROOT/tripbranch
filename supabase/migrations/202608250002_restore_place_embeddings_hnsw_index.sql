begin;

-- place_embeddings_embedding_hnsw_idx가 202608180001에서 만들어졌지만
-- 2026-08-25 확인 시 실제 DB에는 없었다(pg_indexes 조회로 확인 —
-- pkey·content_source_ref_unique·content_id_idx 3개뿐). 2026-08-20 중구
-- RAG 확장 실험(backend/scripts/import_place_embeddings.py) 당시 HNSW
-- 인덱스가 걸린 상태에서 upsert하면 인덱스 갱신 비용 때문에 매 요청이
-- statement_timeout(57014)에 걸리는 문제가 있었고, 이를 우회하려고 인덱스를
-- 지운 뒤 다시 만들지 않은 것으로 보인다(정확한 경위를 남긴 기록은 없음).
--
-- 지금은 57,331건(장소 1,516곳)이 이 인덱스 없이 쌓여 있어, 후보를 먼저
-- content_id로 좁히지 않는 전역 최근접 이웃 검색(§2.10)은 전부 순차
-- 스캔을 탄다. RAG는 아직 추천 파이프라인에 노출되지 않아 지금 당장 장애는
-- 아니지만, 나중에 다시 빠뜨리지 않도록 인덱스 존재 자체를 이 마이그레이션
-- 파일로 남겨 이력을 명시적으로 기록한다.
create index if not exists place_embeddings_embedding_hnsw_idx
  on public.place_embeddings
  using hnsw (embedding vector_cosine_ops);

commit;
