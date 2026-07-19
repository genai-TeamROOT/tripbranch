# TripBranch

TripBranch is a minimal team scaffold for a travel fallback recommendation app.

The current default branch intentionally uses stubbed backend responses. It exists so frontend,
backend, provider, and recommendation-domain teammates can start from a small working app before
designing the real implementation.

## Current User Flow

```text
Free text input
-> fixed interpreted conditions
-> confirmation screen
-> fixed recommendation results
-> results screen
-> show other places
-> start again
```

## Stack

- Backend: Python 3.11+, FastAPI, Pydantic, pytest, Ruff
- Frontend: Node.js 20+, React, TypeScript, Vite, React Router, Tailwind CSS, Vitest
- Root orchestration: npm + concurrently

## Project Structure

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
   │  ├─ pages/
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

## Setup

Install root dependencies:

```bash
npm ci
```

Create and activate the backend environment:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cd ..
```

Windows activation:

```powershell
backend\.venv\Scripts\Activate.ps1
```

Install frontend dependencies:

```bash
cd frontend
npm ci
cp .env.example .env
cd ..
```

The root backend commands use the currently active `python`. Activate the backend virtual
environment before running root scripts.

## Commands

```bash
npm run dev
npm run lint
npm run test
npm run build
```

`npm run dev` starts:

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Swagger/OpenAPI: http://localhost:8000/docs

The Vite dev server proxies `/api/*` to the FastAPI backend.

## Backend Stub Contract

`POST /api/interpret` returns fixed interpreted conditions for any non-empty input:

```json
{
  "location_query": "경복궁",
  "preferred_categories": ["museum", "cafe"],
  "weather_condition": "bad",
  "search_radius_km": 1.0
}
```

`POST /api/recommendations` returns fixed place cards and filters out IDs listed in
`shown_place_ids`.

Implemented endpoints:

- `GET /api/health`
- `POST /api/interpret`
- `POST /api/recommendations`

Current error envelope:

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

## Frontend State

The frontend keeps only the state needed for the stub flow:

- `user_input`
- `interpreted_conditions`
- `recommendations`
- `unverified_recommendations`
- `shown_place_ids`

`sessionStorage` restores the current tab after refresh.

## Deferred Team Work

The detailed recommendation prototype was archived in Git before this scaffold was reduced. Restore
it from the archive commit/branch when you need reference code.

Recommended implementation order:

1. Replace stub recommendation results with a Place Provider contract.
2. Add geocoding provider and location resolution.
3. Add distance filtering.
4. Add operating-hours parsing and current open/closed/unknown status.
5. Add weather provider and weather-to-environment matching.
6. Add weighted scoring.
7. Add deterministic sorting and shown-place exclusion.
8. Add candidate shortage handling.
9. Add real provider implementations.

Reference scoring rules to preserve for the future implementation:

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

Weather/environment score table:

| weather | indoor | mixed | outdoor | unknown |
| --- | ---: | ---: | ---: | ---: |
| good | 0.8 | 0.9 | 1.0 | 0.7 |
| neutral | 1.0 | 0.9 | 0.8 | 0.7 |
| bad | 1.0 | 0.7 | 0.3 | 0.5 |

## Out Of Scope In This Scaffold

- Real LLM interpretation
- Real geocoding/weather/place APIs
- Distance, operating-hour, weather, score, and sorting logic
- OpenAPI TypeScript generation
- Production static file serving
- Database, login, Docker, and automatic condition relaxation
