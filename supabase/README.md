# Supabase 마이그레이션 관리

## 현재 적용 상태

- 대상 프로젝트: TripBranch (`llpcmlzumqkafpsvmyrb`)
- 최초 마이그레이션:
  `202607240001_create_place_tables.sql`
- 후속 마이그레이션:
  `202607240002_add_place_sync_locks.sql`
- 실제 DB 적용일: 2026-07-24
- 적용 방법: Supabase Dashboard SQL Editor에서 수동 실행
- 적용 결과: `places`, `place_enrichments`, `place_sync_runs`,
  `place_sync_locks` 및 잠금 RPC 생성 완료

SQL Editor로 실행했기 때문에 실제 스키마는 생성됐지만 Supabase CLI의 원격
마이그레이션 이력에는 `202607240001`, `202607240002`가 아직 기록되지 않았다.

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

두 버전이 로컬과 원격에서 모두 적용된 상태로 표시된 것을 확인한 뒤에만
`supabase db push`를 사용한다.

## 주의사항

- `202607240001_create_place_tables.sql`을 현재 프로젝트에 다시 실행하지 않는다.
  테이블과 관련 객체가 이미 존재하므로 중복 생성 오류가 발생한다.
- `202607240002_add_place_sync_locks.sql`도 현재 프로젝트에 다시 실행하지 않는다.
- 기존 마이그레이션 파일은 적용 후 수정하지 않는다.
- 이후 스키마 변경은 새 타임스탬프를 가진 마이그레이션 파일로 추가한다.
- 새 마이그레이션은 가능한 한 Supabase CLI `db push` 또는 MCP
  `apply_migration`으로 적용해 원격 이력과 함께 관리한다.
