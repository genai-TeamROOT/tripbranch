# TripBranch 개발 가이드

## 1. 요구 환경

- Node.js 20 이상 (`package.json`의 `engines` 기준)
- Python 3.11 이상 (`backend/pyproject.toml` 기준)
- npm
- macOS/Linux 명령을 기준으로 작성; Windows는 가상환경 활성화 명령이 다름

## 2. 최초 설치

```bash
git clone <repository-url>
cd TripBranch
npm ci

cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
cd ..

cd frontend
npm ci
cp .env.example .env
cd ..
```

저장소 원격 URL은 환경마다 다르므로 `<repository-url>`로 표시했습니다.

Windows PowerShell 가상환경 활성화:

```powershell
backend\.venv\Scripts\Activate.ps1
```

## 3. 환경변수

### Backend

실제 값은 `backend/.env`에 두며 커밋하지 않습니다.

| 변수 | 기본/예시 | 현재 사용 |
| --- | --- | --- |
| `APP_ENV` | `local` | 설정값 보관 |
| `PROVIDER_MODE` | `fake` | Provider 공통 Fake/Real 모드 |
| `GEOCODING_PROVIDER` | 빈 값 | Geocoding 개별 Override |
| `WEATHER_PROVIDER` | 빈 값 | Weather 개별 Override |
| `PLACE_PROVIDER` | 빈 값 | Place 개별 Override |
| `CONCENTRATION_PROVIDER` | 빈 값 | Concentration 개별 Override |
| `HOLIDAY_PROVIDER` | 빈 값 | Holiday 개별 Override |
| `LLM_PROVIDER` | `fake` | 예약 설정; 실제 LLM 미연결 |
| `NAVER_MAP_CLIENT_ID` | 빈 값 | Real Geocoding |
| `NAVER_MAP_CLIENT_SECRET` | 빈 값 | Real Geocoding |
| `WEATHER_API_KEY` | 빈 값 | Real Weather |
| `TOUR_API_SERVICE_KEY` | 빈 값 | Place, Concentration, Holiday |
| `LLM_API_KEY` | 빈 값 | 예약 설정; 현재 미사용 |
| `DATABASE_URL` | 빈 값 | 예약 설정; 현재 미사용 |
| `EXTERNAL_API_TIMEOUT_SECONDS` | `10` | Real Provider timeout |
| `EXTERNAL_API_RETRY_COUNT` | `2` | 설정은 있으나 재시도 로직 미구현 |
| `FAKE_WEATHER_CONDITION` | `neutral` | Fake Weather 결과 |
| `FAKE_CURRENT_DATETIME` | 고정 ISO 시각 | 예약값; 현재 추천 로직에서 미사용 |

`PROVIDER_MODE=real`이면 개별 값이 비어 있는 모든 Provider가 Real 모드가 됩니다.
특정 Provider만 Fake로 유지하려면 예를 들어 `PLACE_PROVIDER=fake`를 지정합니다.

API 키는 채팅, 로그, 테스트 traceback, 커밋에 포함하지 않습니다. 새 키 환경변수를
도입할 때는 `app/config.py`, `.env.example`, 실제 로컬 `.env`의 변수명을 함께
정리하되 `.env`의 값은 공유하지 않습니다.

### Frontend

| 변수 | 기본/예시 | 설명 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | 빈 값 | 비우면 동일 출처 `/api` 사용 |
| `VITE_SHOW_INTERPRETATION_DEBUG` | `true` | Interpret 디버그 카드 표시 |

`VITE_` 값은 브라우저 번들에 포함되므로 비밀정보를 넣지 않습니다. 변경 후 Vite
개발 서버를 재시작합니다.

## 4. 로컬 실행

루트에서 Backend 가상환경을 활성화한 뒤 실행합니다.

```bash
source backend/.venv/bin/activate
npm run dev
```

이 명령은 다음 서버를 함께 실행합니다.

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`

개별 실행이 필요하면 각 `package.json`과 `scripts/dev.mjs`를 기준으로 하며,
문서에 별도의 미확인 명령은 추가하지 않습니다.

## 5. 일반 검사

루트 통합 명령:

```bash
npm run lint
npm run test
npm run build
```

Backend만 검사:

```bash
cd backend
python -m ruff check app tests
python -m pytest -q
```

Frontend만 검사:

```bash
cd frontend
npm run lint
npm run test -- --run
npm run build
```

## 6. Provider 테스트

일반 pytest는 `tests/conftest.py`에 의해 로컬 `.env`가 Real이어도 Fake/Mock
Provider를 사용합니다. 실제 외부 API는 명시적 marker와 환경 플래그로만 호출합니다.

```bash
cd backend

# 전체 Mock/단위 테스트
python -m pytest -q

# 모든 실제 Smoke Test
RUN_REAL_PROVIDER_TESTS=true python -m pytest -m smoke -v -s

# 마스킹된 요청과 원본 응답 확인
RUN_REAL_PROVIDER_INSPECTION=true python -m pytest -m inspection -v -s
```

특정 장소 상세정보 확인:

```bash
RUN_REAL_PROVIDER_INSPECTION=true python -m pytest \
  tests/test_provider_inspection.py::test_inspect_tour_api_keyword_and_details_request_and_response \
  -v -s
```

공휴일 확인:

```bash
RUN_REAL_PROVIDER_INSPECTION=true python -m pytest \
  tests/test_provider_inspection.py::test_inspect_kasi_holiday_request_and_response \
  -v -s
```

전체 명령은 [`backend/docs/provider-test-guide.md`](../backend/docs/provider-test-guide.md)를
참고합니다.

## 7. 코드 구조와 구현 규칙

- 공개 HTTP 모델은 `backend/app/schemas.py`에 둡니다.
- 외부 API와 독립적인 Provider 모델은 `backend/app/domain/models.py`에 둡니다.
- Provider 계약은 `backend/app/providers/protocols.py`에 정의합니다.
- Real/Fake 구현은 동일한 비동기 계약을 지켜야 합니다.
- 외부 응답 필드 차이는 Provider/Mapper에서 흡수합니다.
- 서비스·추천 코드는 Provider 원본 JSON/XML을 직접 사용하지 않습니다.
- 새로운 Real Provider에는 Mock 단위 테스트, Smoke Test, Inspection Test를 함께 둡니다.
- Inspection 출력에서는 query/header 인증정보를 마스킹합니다.
- Frontend API 타입은 현재 수동 관리 중이며 OpenAPI 자동 생성은 `TBD`입니다.

## 8. 개발 흐름 권장안

1. 관련 문서와 현재 계약 확인
2. Fake/Protocol부터 변경해 호출부 계약 확정
3. Real Provider/Service 구현
4. 단위 테스트와 오류 케이스 추가
5. Ruff, Backend/Frontend 테스트 실행
6. 실제 API가 필요한 경우에만 Smoke/Inspection 실행
7. API 키와 `.env`가 스테이징되지 않았는지 확인
8. 관련 변경만 선별 커밋

브랜치·PR naming 규칙과 필수 리뷰 인원은 저장소에서 확인되지 않아 `TBD`입니다.

## 9. 현재 알려진 제약

- 실제 Interpret는 미구현이며 고정 결과를 반환합니다.
- Fake/Fake 추천은 고정 응답이며 실제 Provider 파이프라인과 경로가 다릅니다.
- 가중치 Scoring, 운영시간 계산, 이동시간 계산은 미구현입니다.
- Weather, Concentration, Holiday Provider는 추천 서비스에 아직 연결되지 않았습니다.
- `EXTERNAL_API_RETRY_COUNT`는 설정만 있고 실제 재시도에 사용되지 않습니다.
- Frontend는 목표의 `localStorage`가 아니라 현재 `sessionStorage`를 사용합니다.
- Supabase, 인증, 배포, Docker 구성은 없습니다.
