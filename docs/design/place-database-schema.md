# 장소 데이터베이스 설계 v0.1

## 1. 범위

TripBranch MVP에서 TourAPI 장소 데이터를 미리 수집해 추천 요청 시 재사용하기
위한 장소 영역 스키마를 정의한다. 최초 수집 범위는 종로구지만, 동일한 구조로
다른 시·군·구를 추가할 수 있어야 한다.

이번 설계 범위는 장소 데이터·실행·집중률 매핑과 동기화 제어 테이블이다.

- `places`: TourAPI 장소 기본정보와 운영정보 캐시
- `place_enrichments`: TripBranch가 관리하는 추천용 보완정보
- `place_concentration_mappings`: 집중률 API 장소명과 TourAPI 장소 연결
- `place_sync_runs`: 종로구 장소 동기화 작업 이력
- `place_sync_locks`: 동일 지역 동기화의 중복 실행 방지

추천 실행 및 사용자 피드백 테이블은 이 문서의 범위에서 제외한다.

## 2. 설계 원칙

1. TourAPI에서 받은 데이터와 TripBranch가 직접 관리하는 데이터를 분리한다.
2. 운영시간과 휴무일은 원문과 정규화 결과를 함께 보존한다.
3. 장소별 상세조회 시각과 전체 동기화 실행 시각을 구분한다.
4. 목록에서 사라진 장소는 즉시 삭제하지 않고 `is_active=false`로 처리한다.
5. 프론트엔드는 테이블에 직접 쓰지 않고 FastAPI 백엔드를 통해 접근한다.
6. 동기화는 전체 재수집보다 TourAPI `modifiedtime` 기반 증분 갱신을 우선한다.

## 3. 관계

```text
place_sync_runs 1 ───── N places
                            │
                            │ 1
                            │
                            0..1
                     place_enrichments

places 1 ───── 0..1 place_concentration_mappings

place_sync_runs 1 ───── 0..1 place_sync_locks
```

- 장소는 마지막으로 처리된 동기화 실행을 선택적으로 참조한다.
- 실행 중인 지역에는 최대 하나의 동기화 잠금만 존재한다.
- 장소 하나에는 보완정보가 없거나 한 건 존재한다.
- 장소 하나에는 집중률 대표명과 선택적인 별칭 매핑이 최대 한 건 존재한다.
- 집중률 API에 고유 ID가 없어 `places.content_id`를 매핑의 PK로 사용한다.
- 동기화 실행을 삭제해도 장소는 삭제하지 않는다.
- 장소를 삭제하면 연결된 보완정보는 함께 삭제한다.

## 4. `place_sync_runs`

한 시·군·구의 전체 목록 및 상세정보 동기화 작업 한 번의 실행 상태를 기록한다.
최초 운영 대상은 서울특별시 종로구다.

| 컬럼 | PostgreSQL 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `id` | `uuid` | 필수 | 실행 ID, 기본값 `gen_random_uuid()` |
| `area_code` | `text` | 필수 | TourAPI 법정동 시도 코드. 서울 `11` |
| `district_code` | `text` | 필수 | TourAPI 법정동 시군구 코드. 종로구 `110` |
| `started_at` | `timestamptz` | 필수 | 실행 시작 시각 |
| `completed_at` | `timestamptz` | 선택 | 실행 종료 시각 |
| `status` | `text` | 필수 | `running`, `success`, `partial_failure`, `failed` |
| `api_total_count` | `integer` | 선택 | 목록 API가 보고한 전체 건수 |
| `processed_count` | `integer` | 필수 | 처리 시도한 장소 수 |
| `success_count` | `integer` | 필수 | 정상 처리한 장소 수 |
| `failed_count` | `integer` | 필수 | 처리 실패한 장소 수 |
| `new_count` | `integer` | 필수 | 새로 추가한 장소 수 |
| `updated_count` | `integer` | 필수 | 갱신한 장소 수 |
| `deactivated_count` | `integer` | 필수 | 비활성화한 장소 수 |
| `error_summary` | `jsonb` | 선택 | 오류 코드별 건수 등 실행 단위 요약 |
| `created_at` | `timestamptz` | 필수 | 행 생성 시각 |

### 제약조건

- 모든 건수는 `0` 이상이어야 한다.
- `completed_at`은 `started_at`보다 빠를 수 없다.
- 종료 상태인 실행은 `completed_at`을 가져야 한다.
- `success` 상태에서는 `failed_count=0`이어야 한다.

`error_summary`에는 Service Key, 전체 요청 URL, 사용자 입력 등 비밀정보나
불필요한 원본 데이터를 저장하지 않는다.

예:

```json
{
  "DETAIL_TIMEOUT": 2,
  "DETAIL_EMPTY": 5
}
```

### 4.1 `place_sync_locks`

동일한 시·군·구의 동기화 작업이 동시에 실행되지 않도록 지역별 잠금 한 건을
관리한다.

| 컬럼 | PostgreSQL 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `area_code` | `text` | 필수 | 잠금 대상 시도 코드, 복합 PK |
| `district_code` | `text` | 필수 | 잠금 대상 시군구 코드, 복합 PK |
| `sync_run_id` | `uuid` | 필수 | 잠금을 소유한 실행 ID, Unique 및 FK |
| `acquired_at` | `timestamptz` | 필수 | 잠금 획득 시각 |
| `expires_at` | `timestamptz` | 필수 | 비정상 종료에 대비한 만료 시각 |

잠금 획득과 해제는 테이블 직접 조작 대신 다음 DB 함수를 사용한다.

```text
try_acquire_place_sync_lock(...)
release_place_sync_lock(...)
```

- 동일 지역에 유효한 잠금이 있으면 새 실행의 획득 요청은 `false`를 반환한다.
- 기본 잠금 TTL은 2시간이다.
- 만료된 잠금은 새 실행이 원자적으로 교체할 수 있다.
- 교체된 이전 실행이 아직 `running`이면 `failed`로 정리한다.
- 해제 시 지역 코드뿐 아니라 `sync_run_id`도 일치해야 한다.
- 실행 행 삭제 시 연결된 잠금은 `ON DELETE CASCADE`로 제거한다.
- `anon`, `authenticated`에는 테이블과 함수 실행 권한을 부여하지 않는다.

## 5. `places`

`areaBasedList2`에서 가져온 기본정보와 `detailIntro2`에서 가져온 운영정보를
저장한다. `content_id`를 TourAPI 내 장소 식별자로 사용한다.

| 컬럼 | PostgreSQL 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `content_id` | `text` | 필수 | TourAPI `contentid`, PK |
| `content_type_id` | `text` | 필수 | TourAPI `contenttypeid` |
| `title` | `text` | 필수 | 장소명 |
| `address` | `text` | 선택 | `addr1`, `addr2`를 정리한 주소 |
| `latitude` | `double precision` | 선택 | TourAPI `mapy` |
| `longitude` | `double precision` | 선택 | TourAPI `mapx` |
| `area_code` | `text` | 필수 | TourAPI 법정동 시도 코드 |
| `district_code` | `text` | 필수 | TourAPI 법정동 시군구 코드 |
| `lcls_systm1` | `text` | 선택 | TourAPI 신분류 대분류 코드 |
| `lcls_systm2` | `text` | 선택 | TourAPI 신분류 중분류 코드 |
| `lcls_systm3` | `text` | 선택 | TourAPI 신분류 소분류 코드 |
| `operating_hours_raw` | `text` | 선택 | 유형별 운영시간 원문 |
| `rest_date_raw` | `text` | 선택 | 유형별 휴무일 원문 |
| `operating_schedule` | `jsonb` | 선택 | 현재 파서가 만든 정규화 결과 |
| `operating_parse_status` | `text` | 필수 | `parsed`, `partial`, `unknown`, `assumed` |
| `operating_parser_version` | `text` | 필수 | 정규화 코드 버전 |
| `source_modified_at` | `timestamptz` | 선택 | TourAPI `modifiedtime` |
| `list_fetched_at` | `timestamptz` | 필수 | 목록 API에서 마지막으로 확인한 시각 |
| `detail_fetched_at` | `timestamptz` | 선택 | 상세 API를 마지막으로 정상 조회한 시각 |
| `last_seen_at` | `timestamptz` | 필수 | 최신 목록에서 존재를 확인한 시각 |
| `detail_fetch_status` | `text` | 필수 | `pending`, `success`, `empty`, `failed` |
| `detail_error_code` | `text` | 선택 | 마지막 상세조회 실패의 내부 오류 코드 |
| `is_active` | `boolean` | 필수 | 추천 후보 사용 여부 |
| `inactive_reason` | `text` | 선택 | 비활성 사유 |
| `inactive_at` | `timestamptz` | 선택 | 비활성 전환 시각 |
| `last_sync_run_id` | `uuid` | 선택 | 마지막 처리 실행 FK |
| `created_at` | `timestamptz` | 필수 | 최초 생성 시각 |
| `updated_at` | `timestamptz` | 필수 | 마지막 DB 갱신 시각 |

### 운영정보 JSON 계약

`operating_schedule`은 현재
`backend/app/domain/operating_hours.py::OperatingSchedule`의 직렬화 결과를
기준으로 한다.

```json
{
  "availability": "scheduled",
  "rules": [
    {
      "months": null,
      "weekdays": null,
      "time_ranges": [
        {
          "start": "09:00",
          "end": "18:00",
          "crosses_midnight": false
        }
      ],
      "last_admission": "17:00",
      "source_text": "09:00~18:00, 입장마감 17:00"
    }
  ],
  "closure_rules": [
    {
      "weekdays": [1],
      "source_text": "매주 화요일"
    }
  ],
  "assumption_reason": null,
  "warnings": []
}
```

- 요일은 Python `datetime.weekday()`와 동일하게 월요일 `0`부터 일요일 `6`을
  사용한다.
- `availability`는 `scheduled`, `all_day`, `unknown` 중 하나다.
- 파싱 결과가 `partial`, `unknown`, `assumed`이면 추천 로직에서 영업 중이라고
  확정하지 않는다.
- 파서 개선 시 원문을 사용해 재처리하고 `operating_parser_version`을 변경한다.

### 파서 버전 관리

- 최초 파서 버전은 `operating-hours-1.0.0`으로 시작한다.
- 현재 파서 버전은 백엔드 코드의
  `OPERATING_PARSER_VERSION` 상수로 관리한다.
- 각 장소를 마지막으로 처리한 버전은
  `places.operating_parser_version`에 저장한다.
- 버전은 `operating-hours-MAJOR.MINOR.PATCH` 형식을 사용한다.
  - `MAJOR`: `operating_schedule` JSON 구조의 비호환 변경
  - `MINOR`: 새로운 운영시간·휴무 문구 해석 기능 추가
  - `PATCH`: 기존 파싱 동작의 오류 수정
- DB 버전이 현재 코드 버전과 다른 장소는 저장된 `operating_hours_raw`와
  `rest_date_raw`를 사용해 다시 파싱한다. 이 작업에는 TourAPI 재호출이 필요하지
  않다.
- 새 파서가 정상 실행됐다면 결과가 `unknown`이어도 새 버전을 기록한다.
- 재파싱 작업 자체가 예외로 실패하면 기존 정규화 결과와 버전을 유지한다.
- MVP에서는 별도의 파서 버전 또는 파싱 실행 이력 테이블을 만들지 않는다.

### 제약조건

- `content_id`와 `title`은 빈 문자열일 수 없다.
- 위도는 `-90..90`, 경도는 `-180..180` 범위여야 한다.
- `lcls_systm2`가 있으면 `lcls_systm1`도 있어야 한다.
- `lcls_systm3`가 있으면 `lcls_systm1`, `lcls_systm2`가 모두 있어야 한다.
- `last_sync_run_id`는 `place_sync_runs.id`를 참조하고 삭제 시 `NULL`로 바꾼다.
- `detail_fetch_status='success'`이면 `detail_fetched_at`이 있어야 한다.
- `detail_fetch_status!='failed'`이면 `detail_error_code`는 `NULL`이어야 한다.
- `is_active=true`이면 `inactive_reason`, `inactive_at`은 모두 `NULL`이어야 한다.
- `is_active=false`이면 `inactive_reason`, `inactive_at`이 모두 있어야 한다.
- `inactive_reason`은 `missing_from_source`, `closed`, `moved_outside_area`,
  `invalid_data`, `manual_exclusion` 중 하나다.

## 6. `place_enrichments`

TourAPI에 없거나 추천에 바로 사용하기 어려운 TripBranch 자체 속성을 저장한다.
동기화 작업은 이 테이블의 값을 덮어쓰지 않는다.

| 컬럼 | PostgreSQL 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `content_id` | `text` | 필수 | PK이자 `places.content_id` FK |
| `place_type` | `text` | 필수 | TripBranch 장소 대분류 |
| `place_tags` | `text[]` | 필수 | TripBranch 장소 세부 분류, 기본값 빈 배열 |
| `estimated_visit_minutes` | `integer` | 선택 | 예상 체류시간 |
| `recommendation_tags` | `text[]` | 필수 | 조용함·사진·산책 등 비분류 추천 특성, 기본값 빈 배열 |
| `weather_tags` | `text[]` | 필수 | 날씨 태그, 기본값 빈 배열 |
| `reservation_required` | `boolean` | 선택 | 예약 필요 여부 |
| `source_type` | `text` | 필수 | `manual_research`, `external_data`, `derived` |
| `verified_at` | `timestamptz` | 선택 | 사람이 마지막으로 확인한 시각 |
| `created_at` | `timestamptz` | 필수 | 최초 생성 시각 |
| `updated_at` | `timestamptz` | 필수 | 마지막 수정 시각 |

### 제약조건

- `estimated_visit_minutes`는 값이 있다면 `0`보다 커야 한다.
- 배열에는 `NULL` 원소나 빈 문자열을 넣지 않는다.
- 장소 삭제 시 보완정보는 `ON DELETE CASCADE`로 함께 삭제한다.
- `place_type`은 기존 추천 공통 계약의 `attraction`, `cultural_facility`,
  `festival`, `leisure`, `shopping`, `restaurant` 중 하나다.
- `place_tags`는 `docs/design/int-01-recommend.md`의 `PlaceTag` 코드와
  신분류 매핑을 따른다.
- `place_type`과 `place_tags`는 점수 Feature가 아니라 추천 후보의 1차 하드
  필터에 사용한다.

## 6.1 `place_concentration_mappings`

집중률 API 장소명과 TourAPI 장소를 연결한다. 매칭된 장소만 DB에 저장하고,
미매칭 항목은 검증 CSV에서 관리한다.

| 컬럼 | PostgreSQL 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `content_id` | `text` | 필수 | PK이자 `places.content_id` FK |
| `primary_concentration_name` | `text` | 필수 | 집중률 조회 시 우선 사용할 대표명 |
| `concentration_aliases` | `text[]` | 필수 | 대표명 조회 실패 시 사용할 별칭 |
| `match_method` | `text` | 필수 | `exact`, `normalized`, `manual`, `exact_with_alias` |
| `confidence_score` | `numeric(5,4)` | 선택 | `0` 이상 `1` 이하의 매핑 신뢰도 |
| `verified_at` | `timestamptz` | 선택 | 수동 검증 시각 |
| `created_at` | `timestamptz` | 필수 | 최초 생성 시각 |
| `updated_at` | `timestamptz` | 필수 | 마지막 수정 시각 |

대표명과 별칭이 모두 응답에 있으면 대표명의 집중률을 우선한다. 예를 들어
`content_id=126533`은 `청와대 앞길`을 대표명으로, `청와대`를 별칭으로 사용한다.
장소가 물리 삭제되면 매핑도 `ON DELETE CASCADE`로 제거되지만,
`is_active=false`인 장소는 매핑 입력 대상에서 제외한다.

2026-07-29 최초 적재 기준은 다음과 같다.

- 매핑 행: 100개
- 대표명과 별칭을 합친 집중률 장소: 101개
- 미매칭: 12개
- 비활성 장소 참조: 0개

## 7. 인덱스

기본 PK·FK 인덱스 외에 다음을 둔다.

```text
places (is_active)
places (area_code, district_code) WHERE is_active = true
places (content_type_id) WHERE is_active = true
places (lcls_systm3) WHERE is_active = true
places (source_modified_at)
places (detail_fetch_status, detail_fetched_at)
places (last_sync_run_id)
place_sync_runs (started_at DESC)
place_sync_runs (area_code, district_code, started_at DESC)
place_enrichments USING GIN (recommendation_tags)
place_enrichments (place_type)
place_enrichments USING GIN (place_tags)
```

장소명 부분검색이 실제 요구사항이 된 뒤에만 `pg_trgm` 확장과 GIN 인덱스를
추가한다. 882건 규모에서 미리 추가할 필요는 없다.

## 8. 동기화 규칙

### 전체 흐름

1. `place_sync_runs`에 `running` 실행을 생성한다.
2. `areaBasedList2`의 모든 페이지를 조회한다.
3. 각 장소를 `content_id` 기준으로 `places`에 upsert한다.
4. 신규 장소 또는 `source_modified_at`이 변경된 장소의 `detailIntro2`를 조회한다.
5. 운영정보 원문을 저장하고 현재 파서로 정규화한다.
6. 이번 실행에서 보이지 않은 기존 종로구 장소를 바로 삭제하지 않고
   `is_active=false`로 바꾼다.
7. 처리 건수를 집계하고 실행 상태를 종료 상태로 변경한다.

### 실행 주기

- 정기 동기화는 주 1회 실행한다.
- 매 실행은 `area_code`, `district_code`로 지정한 시·군·구 하나의 전체 목록을
  조회한다.
- 신규 장소 또는 TourAPI `modifiedtime`이 변경된 장소만 상세정보를 다시
  조회한다.
- 마지막 상세조회 후 30일 이상 지난 장소는 `modifiedtime` 변경이 없어도
  상세정보를 다시 확인한다.
- 운영정보가 시급하게 변경된 장소는 정기 실행을 기다리지 않고 단건 수동
  동기화를 허용한다.
- 실패 장소는 다음 주 정기 실행에서 다시 시도하며, 필요하면 단건 수동
  재시도한다.

### 실패 처리

- 장소 하나의 상세조회 실패가 전체 목록 동기화를 롤백시키지 않는다.
- 일부 실패가 있으면 실행은 `partial_failure`로 종료한다.
- 실패 장소는 기존 운영정보를 유지하고 `detail_fetch_status='failed'`와
  `detail_error_code`만 갱신한다.
- API에서 빈 상세정보를 정상 반환한 경우는 장애와 구분해 `empty`로 기록한다.
- 재시도는 `failed`, `pending` 또는 TTL이 지난 장소만 대상으로 한다.

### 비활성화 안전장치

API 일시 오류로 전체 장소가 비활성화되는 것을 막기 위해 다음 조건을 모두
만족할 때만 미노출 장소를 비활성화한다.

- 모든 목록 페이지 조회 성공
- API 보고 건수와 실제 고유 `content_id` 수가 일치
- 실행이 목록 단계에서 실패하지 않음

### 비활성 장소 보존

- 비활성 장소는 MVP에서 자동 삭제하지 않고 계속 보존한다.
- 최신의 완전한 목록에서 사라진 장소는 `is_active=false`,
  `inactive_reason='missing_from_source'`로 기록한다.
- `missing_from_source` 장소가 이후 목록에 다시 나타나면 자동으로 활성화한다.
- `closed`, `moved_outside_area`, `invalid_data`, `manual_exclusion` 장소는 목록에
  다시 나타나더라도 자동 활성화하지 않고 팀 확인을 거친다.
- 비활성 장소는 추천 후보 조회에서 제외한다.

## 9. 보안과 Supabase 정책

- 브라우저에 Supabase Secret Key를 노출하지 않는다.
- 동기화 INSERT·UPDATE는 FastAPI 백엔드 또는 관리자 배치만 수행한다.
- MVP에서는 장소 영역 테이블 모두 RLS를 활성화하고 `anon`, `authenticated` 역할에
  직접 쓰기 정책을 만들지 않는다.
- 일반 사용자에게 장소 목록 직접 조회를 열 필요가 생기면 공개 가능한 컬럼만
  노출하는 View 또는 FastAPI API를 사용한다.
- 운영정보 원문에는 HTML이 포함될 수 있으므로 화면 출력 시 sanitize한다.

## 10. 확정 사항과 후속 결정

### v0.1 확정

- 장소 데이터·실행 테이블은 `places`, `place_enrichments`, `place_sync_runs`,
  집중률 매핑은 `place_concentration_mappings`, 중복 실행 제어는
  `place_sync_locks`다.
- 운영정보는 MVP에서 `places`에 포함한다.
- 운영정보 원문과 정규화 JSON을 모두 저장한다.
- 장소별 상세조회 시각과 배치 실행 이력을 모두 보관한다.
- 외부 원본 데이터와 TripBranch 보완정보를 분리한다.
- 운영정보 파서 최초 버전은 `operating-hours-1.0.0`이며, 코드 상수와 장소별
  적용 버전을 비교해 저장된 원문을 재파싱한다.
- 정기 동기화는 주 1회 실행하고, 상세정보는 변경된 장소 또는 마지막 상세조회
  후 30일 이상 지난 장소를 대상으로 갱신한다.
- 비활성 장소는 삭제하지 않고 사유와 비활성 시각을 기록해 계속 보존한다.

### 적용 상태

- 최초 마이그레이션은
  `supabase/migrations/202607240001_create_place_tables.sql`이며 2026-07-24에
  Supabase SQL Editor로 적용했다.
- 동기화 잠금은
  `supabase/migrations/202607240002_add_place_sync_locks.sql`로 같은 날 적용했다.
- SQL Editor 적용으로 원격 마이그레이션 이력은 생성되지 않았으므로, Supabase CLI
  최초 도입 시 `supabase/README.md`의 이력 복구 절차를 먼저 수행한다.
- 집중률 매핑은
  `supabase/migrations/20260729104209_create_place_concentration_mappings.sql`로
  2026-07-29 Supabase MCP를 통해 적용했다.
