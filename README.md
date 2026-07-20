# TripBranch

TripBranch는 여행 중 날씨 악화, 방문 장소 이용 불가, 남은 시간 부족 같은 상황에서 대체 장소를 추천하는 서비스를 만들기 위한 **최소 팀 프로젝트 골격**입니다.

현재 기본 브랜치는 의도적으로 백엔드 응답을 Stub으로 고정해 두었습니다. 프론트엔드, 백엔드, Provider, 추천 도메인 담당자가 실제 구현을 설계하기 전에 작고 실행 가능한 앱에서 출발할 수 있게 하는 것이 목적입니다.

## 현재 사용자 흐름

```text
사용자 자유 입력
-> 고정된 입력 해석 결과
-> 채팅 화면으로 이동
-> 개발 모드: 입력 해석 디버그 메시지 확인 후 추천 진행
-> 릴리즈 모드: 조건 요약 메시지 표시 후 추천 자동 진행
-> 추천 결과 메시지 누적
-> 다른 장소 보기
-> 처음부터 다시 시작
```

TripBranch 프론트엔드는 최종 서비스 UX에 맞춰 페이지를 순서대로 이동하는 구조가 아니라, `/chat` 안에서 사용자 입력과 추천 결과가 시간순으로 쌓이는 채팅형 흐름을 사용합니다.

## 기술 스택

- 백엔드: Python 3.11+, FastAPI, Pydantic, pytest, Ruff
- 프론트엔드: Node.js 20+, React, TypeScript, Vite, React Router, Tailwind CSS, Vitest
- 루트 실행 스크립트: npm + 간단한 Node 스크립트

## 프로젝트 구조

```text
tripbranch/
├─ package.json
├─ package-lock.json
├─ README.md
├─ .gitignore
├─ .github/workflows/ci.yml
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ routes/
│  │  ├─ services/
│  │  ├─ providers/
│  │  ├─ schemas.py
│  │  ├─ config.py
│  │  └─ errors.py
│  ├─ tests/
│  ├─ pyproject.toml
│  └─ .env.example
└─ frontend/
   ├─ src/
   │  ├─ api/
   │  ├─ components/
   │  │  └─ chat/
   │  │     ├─ ChatComposer.tsx
   │  │     ├─ ChatMessageList.tsx
   │  │     ├─ ConditionDebugMessage.tsx
   │  │     └─ RecommendationResultMessage.tsx
   │  ├─ config/
   │  │  └─ features.ts
   │  ├─ pages/
   │  │  ├─ HomePage.tsx
   │  │  └─ ChatPage.tsx
   │  ├─ state/
   │  ├─ test/
   │  ├─ App.tsx
   │  ├─ main.tsx
   │  ├─ index.css
   │  └─ types.ts
   ├─ package.json
   ├─ package-lock.json
   ├─ vite.config.ts
   ├─ eslint.config.js
   └─ .env.example
```

## 설치 방법

루트 의존성을 설치합니다.

```bash
npm ci
```

백엔드 가상환경을 만들고 활성화합니다.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cd ..
```

Windows PowerShell에서는 다음 명령으로 가상환경을 활성화합니다.

```powershell
backend\.venv\Scripts\Activate.ps1
```

프론트엔드 의존성을 설치합니다.

```bash
cd frontend
npm ci
cp .env.example .env
cd ..
```

루트의 백엔드 관련 명령은 현재 활성화된 `python`을 사용합니다. 루트 스크립트를 실행하기 전에 `backend/.venv`를 활성화해 주세요.

## 실행 명령

```bash
npm run dev
npm run lint
npm run test
npm run build
```

`npm run dev`는 다음 서버를 실행합니다.

- 프론트엔드: http://localhost:5173
- 백엔드: http://localhost:8000
- Swagger/OpenAPI 문서: http://localhost:8000/docs

Vite 개발 서버는 `/api/*` 요청을 FastAPI 백엔드로 프록시합니다.

## 프론트엔드 라우트

현재 프론트엔드 라우트는 다음 두 개가 기본입니다.

- `/`: `HomePage`
- `/chat`: `ChatPage`

기존 전환 과정에서 쓰던 `/confirm`, `/results`는 독립 화면으로 유지하지 않고 `/chat`으로 리다이렉트합니다.

`HomePage`는 최초 질문 입력, 입력 해석 API 호출, 채팅 상태 초기화를 담당합니다. `ChatPage`는 사용자 메시지, 조건 요약/디버그 메시지, 추천 결과 메시지를 시간순으로 렌더링합니다.

## 개발 모드와 릴리즈 모드

프론트엔드는 다음 공개 환경변수로 입력 해석 디버그 카드 노출 여부를 제어합니다.

```env
VITE_SHOW_INTERPRETATION_DEBUG=true
```

- `true`: 개발 모드. `/chat`에서 `ConditionDebugMessage`를 표시하고, 개발자가 구조화된 조건을 확인한 뒤 추천을 진행합니다.
- `false`: 릴리즈 모드. 조건 디버그 카드를 숨기고, 짧은 조건 요약 메시지를 표시한 뒤 추천을 자동 요청합니다.

이 값은 `frontend/src/config/features.ts`에서 읽습니다. `VITE_` 환경변수는 브라우저 빌드 결과에 포함되므로 API 키나 내부 프롬프트 같은 비밀값을 넣으면 안 됩니다.

`frontend/.env.example`은 팀원 참고용 예시 파일입니다. 실제 로컬 개발 서버에는 적용되지 않습니다. 로컬에서 개발 모드를 켜려면 `frontend/.env`에 값을 설정해야 합니다.

```bash
cp frontend/.env.example frontend/.env
```

`.env`를 바꾼 뒤에는 Vite 개발 서버를 재시작해야 합니다.

릴리즈 빌드나 시연 환경에서 디버그 카드를 숨기려면 다음처럼 설정합니다.

```env
VITE_SHOW_INTERPRETATION_DEBUG=false
```

## 프론트엔드 환경변수

| 변수 | 기본/예시 값 | 설명 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | 비움 | 비워두면 동일 출처의 `/api`를 사용합니다. 로컬 개발에서는 Vite 프록시가 백엔드로 전달합니다. |
| `VITE_SHOW_INTERPRETATION_DEBUG` | `true` | `true`면 개발용 입력 해석 디버그 카드를 표시하고, `false`면 조건 요약 후 추천을 자동 진행합니다. |

실제 로컬 실행 값은 `frontend/.env`에 둡니다. `frontend/.env.example`은 팀원이 참고하는 예시 파일이며, Vite dev 서버가 자동으로 적용하는 실행 설정 파일은 아닙니다.

## 수동 동작 확인

로컬 서버를 실행합니다.

```bash
npm run dev
```

개발 모드 확인:

1. `frontend/.env`에 `VITE_SHOW_INTERPRETATION_DEBUG=true`를 설정합니다.
2. dev 서버를 재시작합니다.
3. http://localhost:5173 에서 질문을 입력합니다.
4. `/chat`으로 이동한 뒤 `개발용 입력 해석 결과` 카드가 보이는지 확인합니다.
5. `추천 진행` 버튼을 눌러 추천 결과 메시지가 추가되는지 확인합니다.

릴리즈 모드 확인:

1. `frontend/.env`에 `VITE_SHOW_INTERPRETATION_DEBUG=false`를 설정합니다.
2. dev 서버를 재시작합니다.
3. 질문을 입력합니다.
4. `/chat`에서 개발용 디버그 카드가 보이지 않는지 확인합니다.
5. 조건 요약 메시지 뒤에 추천 결과가 자동으로 표시되는지 확인합니다.

공통 확인:

1. 추천 결과에서 `다른 장소 보기`를 누릅니다.
2. 기존 추천 결과가 사라지지 않고 새 추천 결과 메시지가 대화 하단에 추가되는지 확인합니다.
3. `/chat`에서 새로고침했을 때 같은 탭의 대화가 복구되는지 확인합니다.
4. `처음부터` 버튼을 누르면 저장된 대화가 초기화되고 `/`로 돌아가는지 확인합니다.

## 백엔드 Stub 계약

`POST /api/interpret`는 비어 있지 않은 모든 입력에 대해 고정된 조건 해석 결과를 반환합니다.

```json
{
  "location_query": "경복궁",
  "preferred_categories": ["museum", "cafe"],
  "weather_condition": "bad",
  "search_radius_km": 1.0
}
```

`POST /api/recommendations`는 고정된 추천 장소 목록을 반환합니다. 요청의 `shown_place_ids`에 포함된 장소 ID는 결과에서 제외됩니다.

현재 구현된 엔드포인트는 다음과 같습니다.

- `GET /api/health`
- `POST /api/interpret`
- `POST /api/recommendations`

현재 공통 오류 응답 형식은 다음과 같습니다.

```json
{
  "error": {
    "code": "invalid_request",
    "message": "요청 내용을 확인해주세요.",
    "retryable": false,
    "details": null
  }
}
```

## 프론트엔드 상태

프론트엔드는 채팅 흐름에 필요한 최소 상태만 관리합니다.

- `user_input`
- `interpreted_conditions`
- `recommendations`
- `unverified_recommendations`
- `shown_place_ids`
- `messages`
- `phase`
- `error`

추천 결과는 각 `recommendation_result` 메시지 안에 저장되어 대화 하단에 누적됩니다. 기존 `recommendations`, `unverified_recommendations` 필드는 현재 마지막 추천 결과와의 호환을 위해 함께 유지합니다.

`sessionStorage`를 사용해 같은 탭에서 새로고침해도 현재 대화를 복구합니다. 저장 구조는 버전으로 검증하며, 잘못된 JSON이나 schema가 들어오면 무시합니다.

릴리즈 모드에서는 저장된 `condition_debug` 메시지가 있어도 화면에 렌더링하지 않습니다.

## 이후 팀 작업

상세 추천 프로토타입은 이 골격으로 축소하기 전에 Git에 보존되어 있습니다. 참고 구현이 필요하면 보존 커밋 또는 보존 브랜치에서 복구할 수 있습니다.

- 보존 브랜치: `archive-full-prototype`
- 보존 커밋: `cb75c48 Archive full TripBranch prototype`

권장 구현 순서는 다음과 같습니다.

1. Stub 추천 결과를 Place Provider 계약으로 교체
2. 지오코딩 Provider와 위치 해석 추가
3. 거리 필터 구현
4. 운영시간 파싱과 `open` / `closed` / `unknown` 판정 구현
5. 날씨 Provider와 날씨-환경 유형 매칭 추가
6. 가중치 기반 점수 계산 구현
7. 결정적 정렬과 `shown_place_ids` 제외 처리 구현
8. 후보 부족 처리 구현
9. 실제 Provider 구현 연결

향후 추천 로직 구현 시 보존할 점수 규칙은 다음과 같습니다.

```yaml
weights:
  category: 0.40
  remaining_open_time: 0.30
  weather: 0.20
  distance: 0.10
weights_without_weather:
  category: 0.50
  remaining_open_time: 0.375
  distance: 0.125
category_score:
  rank_1: 1.00
  rank_2: 0.85
  rank_3: 0.70
remaining_open_time:
  180_minutes_or_more: 1.00
  120_to_179: 0.85
  60_to_119: 0.65
  30_to_59: 0.35
  less_than_30: 0.10
distance:
  within_25_percent_of_radius: 1.00
  within_50_percent_of_radius: 0.80
  within_75_percent_of_radius: 0.60
  within_100_percent_of_radius: 0.40
```

날씨와 장소 환경 유형 점수표는 다음과 같습니다.

| 날씨 | indoor | mixed | outdoor | unknown |
| --- | ---: | ---: | ---: | ---: |
| good | 0.8 | 0.9 | 1.0 | 0.7 |
| neutral | 1.0 | 0.9 | 0.8 | 0.7 |
| bad | 1.0 | 0.7 | 0.3 | 0.5 |

## 현재 골격에서 제외된 범위

- 실제 LLM 입력 해석
- 실제 지오코딩, 날씨, 장소 API 연동
- 거리 계산, 운영시간 계산, 날씨 반영, 점수 계산, 정렬 로직
- OpenAPI TypeScript 타입 생성
- production 정적 파일 서빙
- 데이터베이스, 로그인, Docker, 자동 조건 완화
