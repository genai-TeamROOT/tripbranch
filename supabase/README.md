# Supabase 마이그레이션 관리

## 현재 적용 상태

- 대상 프로젝트: TripBranch (`llpcmlzumqkafpsvmyrb`)
- 최초 마이그레이션:
  `202607240001_create_place_tables.sql`
- 후속 마이그레이션:
  `202607240002_add_place_sync_locks.sql`
- 집중률 매핑 마이그레이션:
  `20260729104209_create_place_concentration_mappings.sql`
- 집중률 검색어 컬럼 마이그레이션:
  `202608040001_add_concentration_search_key.sql`
  (원격 이력에는 `20260804055402_add_concentration_search_key`로 기록됨 — MCP가
  적용 시각으로 버전을 붙여 파일명과 다르다)
- 주차·요금·이미지 컬럼 마이그레이션:
  `202608080001_add_place_parking_fee_image_columns.sql`
  (원격 이력에는 `20260808050321_add_place_parking_fee_image_columns`로 기록됨)
  (D-056. `places`에 `parking_info_raw`, `parking_fee_raw`, `use_fee_raw`,
  `discount_info_raw`, `first_image_url`, `thumbnail_url` 추가. 값 적재는
  provider·place_sync 배선 후)
- 집중률 검색어 목록 마이그레이션:
  `202608080002_add_concentration_search_keys.sql`
  (원격 이력에는 `20260808064030_add_concentration_search_keys`로 기록됨)
  (D-057. `concentration_search_keys text[]` 추가·backfill 후 단수 컬럼
  `concentration_search_key`를 삭제한다. 두 컬럼을 병행하면 진실의 원천이 둘이 되므로
  한 마이그레이션에서 끝낸다. 체크 제약에는 서브쿼리를 쓸 수 없어 공백 검사를
  `array_to_string(keys, ',') !~ '\s'`로 우회한다)
- 실제 DB 적용일: 2026-07-24, 2026-07-29, 2026-08-04, 2026-08-08
- 적용 방법: Supabase Dashboard SQL Editor 및 Supabase MCP `apply_migration`
- 적용 결과: `places`, `place_enrichments`, `place_sync_runs`,
  `place_sync_locks`, `place_concentration_mappings` 및 잠금 RPC 생성 완료

SQL Editor로 실행했기 때문에 실제 스키마는 생성됐지만 Supabase CLI의 원격
마이그레이션 이력에는 `202607240001`, `202607240002`가 아직 기록되지 않았다.
`20260729104209`와 `20260804055402`는 Supabase MCP로 적용해 원격 마이그레이션 이력에
기록됐다.

## Supabase CLI 최초 도입 시 필수 작업

프로젝트를 CLI에 연결한 뒤, 최초 마이그레이션을 다시 실행하지 말고 이미 적용된
상태로 기록한다.

```bash
supabase migration repair 202607240001 --status applied
supabase migration repair 202607240002 --status applied
```

그다음 원격과 로컬 마이그레이션 이력이 일치하는지 확인한다.

```bash
supabase migration list
```

두 버전이 로컬과 원격에서 모두 적용된 상태로 표시되고,
`20260729104209`도 양쪽에 존재하는지 확인한 뒤에만 `supabase db push`를 사용한다.

## 주의사항

- `202607240001_create_place_tables.sql`을 현재 프로젝트에 다시 실행하지 않는다.
  테이블과 관련 객체가 이미 존재하므로 중복 생성 오류가 발생한다.
- `202607240002_add_place_sync_locks.sql`도 현재 프로젝트에 다시 실행하지 않는다.
- `20260729104209_create_place_concentration_mappings.sql`도 적용 완료 상태이므로
  다시 실행하지 않는다.
- `202608080001_add_place_parking_fee_image_columns.sql`도 적용 완료 상태다.
  `add column if not exists`라 재실행해도 오류는 나지 않지만 다시 실행하지 않는다.
- 기존 마이그레이션 파일은 적용 후 수정하지 않는다.
- 이후 스키마 변경은 새 타임스탬프를 가진 마이그레이션 파일로 추가한다.
- 새 마이그레이션은 가능한 한 Supabase CLI `db push` 또는 MCP
  `apply_migration`으로 적용해 원격 이력과 함께 관리한다.
