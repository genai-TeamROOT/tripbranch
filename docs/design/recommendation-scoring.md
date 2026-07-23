# 추천 점수 설계 (Scoring v1)

## 문서 정보

| 항목 | 값 |
|------|-----|
| 버전 | v1 |
| 상태 | 초안 (Draft) |
| 최종 수정 | 2026-07-23 |
| 관련 코드 | `backend/app/domain/models.py::ScoringCandidate`, `backend/app/domain/scoring.py` |

이 문서는 [`docs/decision-log.md`](../decision-log.md)의 D-008(하드 필터 + 가중치 점수
조합)을 구현 가능한 수준으로 구체화한다. C-01(Tool 계약)이 아직 확정되지 않았으므로
Tool의 실제 출력 대신 `ScoringCandidate` 모델에 맞춘 응답 샘플/Stub 데이터로 작업한다.

---

## 1. 범위

Scoring v1이 다루는 것:

- Provider/Tool 독립적인 `Candidate` 공통 모델 (`ScoringCandidate`)
- 카테고리, 남은 영업시간, 날씨, 거리 4개 Feature
- 폐점/운영시간 미확인/이전 추천·거절 장소의 처리 기준
- 기본 가중치와 날씨 결측 시 재분배 가중치
- 점수 기준 정렬(Ranking) 출력 구조

Scoring v1이 다루지 않는 것 (`TBD`):

- 혼잡도(Concentration) Feature, 분위기/조용함 근거(Evidence confidence)
- 실제 이동시간 기반 거리 계산 (현재는 직선거리 전제)
- 예산·동행·필수 편의시설 하드 필터 (`INT-01`의 Conditions 필드 중 일부)
- 자연어 추천 이유 생성 (Response Generator 영역)

## 2. Candidate Model v1

`backend/app/domain/models.py::ScoringCandidate`

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `place_id` | `str` | 장소 식별자 (Provider의 `PlaceCandidate.place_id`와 동일 값 사용) |
| `name` | `str` | 장소명 |
| `category` | `str` | 내부 카테고리 (`PlaceCandidate.category`와 동일 체계) |
| `environment_type` | `str` | `"indoor"` \| `"outdoor"` \| `"unknown"` |
| `distance_km` | `float` | 검색 기준점(origin)으로부터의 거리 (v1은 직선거리 전제) |
| `place_status` | `PlaceStatus` | `OPEN` \| `CLOSED` \| `UNKNOWN` |
| `remaining_open_minutes` | `int \| None` | 남은 영업시간(분); 상태가 `OPEN`이 아니거나 값을 모르면 `None` |
| `raw_source` | `str` | 후보를 채운 Tool/Provider 식별값 (기본 `"unknown"`) |

`PlaceCandidate`(Provider 산출물)와 별도 모델로 둔 이유는 두 가지다.

1. `PlaceCandidate`는 아직 운영 상태·거리·실내외 구분을 갖지 않는다. 이 값들은
   여러 Tool(`getPlaceDetails`, `estimateTravelTime`, `getCurrentWeather` 등)의
   결과를 조합해야 채워지므로, Provider 하나의 출력 모델에 억지로 넣지 않는다.
2. C-01 Tool 계약이 확정되기 전까지 Scoring이 실제 Tool 구현에 결합되지 않도록,
   Scoring의 입력 경계를 이 모델 하나로 고정한다. Tool이 완성되면
   "Tool 출력 → `ScoringCandidate`" 매퍼만 추가하면 되고 Scoring 내부 로직은
   바뀌지 않는다.

### 김진형의 Tool 결과와 연결

C-01의 Tool 출력 초안이 아직 없으므로, 현재는 아래 대응을 임시 계약으로 가정한다.
실제 Tool 계약이 나오면 이 표를 갱신한다.

| `ScoringCandidate` 필드 | 예상 Tool 출처 |
| --- | --- |
| `place_id`, `name`, `category` | `searchNearbyPlaces` (Place Provider 기반) |
| `distance_km` | `estimateTravelTime` 또는 origin 좌표로 계산한 직선거리 |
| `place_status`, `remaining_open_minutes` | `getPlaceDetails`의 운영시간 파싱 결과 |
| `environment_type` | `category` → 실내외 매핑표 (§4.2) |

## 3. 제외 규칙 (하드 필터)

Scoring 이전에 다음 조건으로 후보를 제외한다. 제외된 항목은 점수를 계산하지 않는다.

| 조건 | 처리 | 이유 |
| --- | --- | --- |
| `place_status == CLOSED` | 제외 | 폐점 장소는 방문 불가능하므로 추천 후보 자체가 아님 |
| `place_id in shown_place_ids` | 제외 | 이미 이번 세션에서 노출한 장소 |
| `place_id in rejected_place_ids` | 제외 | 사용자가 명시적으로 거절한 장소 |

`place_status == UNKNOWN`(운영시간 미확인)은 **제외하지 않는다.** 폐점과 미확인은
다른 상태이며, 미확인 후보는 점수를 계산하되 `is_unverified=True`와 경고 문구를
함께 반환한다. 이는 현재 `services/recommendations.py`가 `operating_hours` 유무로
`recommendations`/`unverified_recommendations`를 나누는 방식과 같은 원칙이다.

## 4. Feature 정의

각 Feature는 0.0~1.0 범위로 정규화한다.

### 4.1 카테고리 (category_score)

`INT-01`의 `place_tags` 언급 순위 규칙을 그대로 사용한다.

```
preferred_categories가 비어 있음        → 1.00 (차등 없음)
candidate.category가 preferred_categories[0]  → 1.00
candidate.category가 preferred_categories[1]  → 0.85
candidate.category가 preferred_categories[2]  → 0.70
candidate.category가 preferred_categories[3:] → 0.60
candidate.category가 목록에 없음         → 0.50 (기본값)
```

### 4.2 남은 영업시간 (remaining_time_score)

```
place_status == UNKNOWN 이거나 remaining_open_minutes is None → 0.50 (중립값)
그 외                                                          → min(remaining_open_minutes / 120, 1.0)
```

2시간(120분) 이상 남아 있으면 만점, 그보다 적으면 비례 감소한다. 남은 시간을 모르는
경우를 0점이 아닌 중립값(0.50)으로 두는 이유는, 운영시간 미확인이 "곧 닫음"을
의미하지 않기 때문이다(폐점과 구분되는 이유와 동일).

`environment_type` 매핑은 카테고리 기준으로 잠정 분류한다 (현재
`services/recommendations.py`의 `_INDOOR_CATEGORIES`/`_OUTDOOR_CATEGORIES`와 동일 기준):

| environment_type | category 예시 |
| --- | --- |
| `indoor` | museum, cafe, gallery, restaurant |
| `outdoor` | park, trail, beach |
| `unknown` | 그 외 |

### 4.3 날씨 적합도 (weather_fit_score)

날씨 정보가 없으면(`weather_condition is None`) 이 Feature 자체를 계산하지 않고
§5의 재분배 규칙을 적용한다. 날씨 정보가 있으면 `environment_type`과 조합한다.

| `WeatherCondition` | indoor | outdoor | unknown |
| --- | --- | --- | --- |
| `GOOD` | 0.70 | 1.00 | 0.85 |
| `NEUTRAL` | 0.80 | 0.80 | 0.80 |
| `BAD` | 1.00 | 0.30 | 0.60 |

### 4.4 거리 (distance_score)

```
distance_score = clamp(1 - distance_km / max_distance_km, 0.0, 1.0)
```

`max_distance_km`는 해당 실행의 검색 반경(`search_radius_km`)을 사용한다. 반경이
0 이하인 방어적인 경우 `distance_km == 0`이면 1.0, 아니면 0.0으로 처리한다.

## 5. 가중치

### 5.1 기본 가중치

| Feature | 기본 가중치 |
| --- | --- |
| 카테고리 | 0.35 |
| 날씨 | 0.25 |
| 남은 영업시간 | 0.25 |
| 거리 | 0.15 |

### 5.2 날씨 정보 없을 때 재분배

날씨 Feature를 제외하고, 날씨 가중치(0.25)를 나머지 세 Feature에 **기존 비중에
비례**하여 재분배한다. 일반식은 다음과 같다.

```
new_weight[f] = weight[f] / (1 - weight[weather])   (f != weather)
```

기본 가중치 기준 재분배 결과:

| Feature | 재분배 가중치 |
| --- | --- |
| 카테고리 | 0.4667 (0.35 / 0.75) |
| 남은 영업시간 | 0.3333 (0.25 / 0.75) |
| 거리 | 0.2000 (0.15 / 0.75) |

카테고리:남은 영업시간:거리 = 35:25:15의 비율은 재분배 후에도 유지된다.

### 5.3 최종 점수

```
score = Σ (feature_score[f] * weight[f])   (날씨 결측 시 f는 weather를 제외한 3개)
```

## 6. 정렬 (Ranking) 및 tie-break

- 1차: `score` 내림차순
- 2차(동점 시): `distance_km` 오름차순
- 3차(그래도 동점 시): `place_id` 오름차순 (결정적 정렬 보장)

## 7. 출력 구조

```python
@dataclass(frozen=True)
class RankedCandidate:
    place_id: str
    name: str
    category: str
    rank: int
    score: float
    feature_scores: Mapping[str, float | None]  # weather는 결측 시 None
    is_unverified: bool
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class ScoringResult:
    ranked: tuple[RankedCandidate, ...]
    weights_used: Mapping[str, float]
    excluded_place_ids: tuple[str, ...]
```

`feature_scores`는 이후 Response Generator/LLM이 추천 이유를 생성할 때 근거로 쓸 수
있도록 Feature별 점수를 그대로 노출한다 (`docs/api-contracts.md`의
`RecommendationResult.featureScores`와 동일한 의도). `reason` 문자열 자체는 Scoring
v1의 책임이 아니며 후속 업무(Response Generator)에서 `feature_scores`를 입력으로
받아 생성한다.

## 8. 관련 문서

- [`docs/decision-log.md`](../decision-log.md) — D-008
- [`docs/architecture.md`](../architecture.md) — Recommendation Engine 책임
- [`docs/api-contracts.md`](../api-contracts.md) — `Candidate`/`RecommendationResult` 목표 계약
- [INT-01: RECOMMEND](./int-01-recommend.md) — 카테고리 점수 규칙 출처
