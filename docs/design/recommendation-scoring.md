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
- 날씨, 남은 운영시간, 거리 3개 Feature
- 폐점(최종 하드 필터)/운영시간 미확인/이전 추천·거절 장소의 처리 기준
- 기본 가중치와 날씨·남은 운영시간 결측 시 재분배 가중치
- 점수 기준 정렬(Ranking) 출력 구조

Scoring v1이 다루지 않는 것 (`TBD`):

- 카테고리 매치 Feature — 1차 하드 필터(place_type/place_tag)가 이미 처리한다고
  보고 Scoring v1의 가중치 계산에서는 제외하기로 결정함 (§4 참고)
- 혼잡도(Concentration) Feature, 분위기/조용함 근거(Evidence confidence)
- 실제 이동시간 기반 거리 계산 (현재는 직선거리 전제)
- 예산·동행·필수 편의시설 하드 필터 (`INT-01`의 Conditions 필드 중 일부)
- 운영시간 원문("0900~1800" 등)을 `OperatingHours`로 정규화하는 파서 자체
  (`PLC-03`과 동일 범위, Tool/Provider 계층 소관)
- 자정을 넘기는 운영시간(예: 22:00~02:00)
- 기준 시각(`now`)의 실제 출처 — 즉시 방문/방문 예정 시각 선택은 D-022 연계 `TBD`
- 자연어 추천 이유 생성 (Response Generator 영역)

## 2. Candidate Model v1

`backend/app/domain/models.py::ScoringCandidate`

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `place_id` | `str` | 장소 식별자 (Provider의 `PlaceCandidate.place_id`와 동일 값 사용) |
| `name` | `str` | 장소명 |
| `category` | `str` | 내부 카테고리 (`PlaceCandidate.category`와 동일 체계); 표시용 메타데이터로만 사용하고 점수 계산에는 쓰지 않음 |
| `environment_type` | `str` | `"indoor"` \| `"outdoor"` \| `"unknown"` |
| `distance_km` | `float` | 검색 기준점(origin)으로부터의 거리 (v1은 직선거리 전제) |
| `operating_hours` | `OperatingHours \| None` | 당일 개장~마감 시각. `None`이면 운영시간 미확인 |
| `raw_source` | `str` | 후보를 채운 Tool/Provider 식별값 (기본 `"unknown"`) |

`OperatingHours`는 `open_time`/`close_time`(`datetime.time`) 두 필드만 가지며,
`open_time <= close_time`인 당일 운영만 다룬다(§1 범위 참고). 운영 유무(폐점
여부)는 이 필드 자체에 boolean으로 저장하지 않고, Scoring이 실행 시점에 받는
기준 시각 `now`와 비교해 직접 판정한다(§3).

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
| `operating_hours` | `getPlaceDetails`의 운영시간 원문을 `OperatingHours`(개장~마감)로 정규화한 결과 |
| `environment_type` | `category` → 실내외 매핑표 (§4.2) |

## 3. 제외 규칙 (하드 필터)

Scoring 실행 시점의 기준 시각 `now`를 입력받아, 다음 조건으로 후보를 제외한다.
제외된 항목은 점수를 계산하지 않는다.

| 조건 | 처리 | 이유 |
| --- | --- | --- |
| `operating_hours`가 있고 `now`가 `[open_time, close_time)` 밖 | 제외(폐점) | 폐점 장소는 방문 불가능하므로 추천 후보 자체가 아님 |
| `place_id in shown_place_ids` | 제외 | 이미 이번 세션에서 노출한 장소 |
| `place_id in rejected_place_ids` | 제외 | 사용자가 명시적으로 거절한 장소 |

운영 유무(폐점 여부)는 더 이상 별도 boolean 필드가 아니라, Scoring이 `now`와
`operating_hours`를 비교해 **최종 하드 필터로 직접 판정**한다. `operating_hours
is None`(운영시간 미확인)은 **제외하지 않는다.** 폐점과 미확인은 다른 상태이며,
미확인 후보는 점수를 계산하되 `is_unverified=True`와 경고 문구를 함께 반환한다.
이는 현재 `services/recommendations.py`가 `operating_hours` 유무로
`recommendations`/`unverified_recommendations`를 나누는 방식과 같은 원칙이다.

카테고리(place_type/place_tag) 일치 여부도 하드 필터의 영역이다. 예를 들어
"카페 아니면 공원"처럼 place_type이 여러 개 허용된 경우 그 안에서의 우선순위는
Scoring이 아니라 상위 Interpret/Filter 단계가 담당하고, Scoring v1은 카테고리
필터를 통과한 후보들 사이에서 날씨·남은 운영시간·거리로 점수를 매긴 뒤 운영
유무로 최종 필터링한다 (§9 참고).

## 4. Feature 정의

각 Feature는 0.0~1.0 범위로 정규화한다.

### 4.1 남은 운영시간 (remaining_operating_time_score)

```
remaining_minutes = (close_time - now)를 분 단위로 계산 (now가 영업시간 안일 때만)
remaining_operating_time_score = clamp(remaining_minutes / 120, 0.0, 1.0)
```

마감까지 120분 이상 남았으면 만점(1.0)으로 취급한다. `now`가 영업시간 밖이면
§3의 하드 필터에서 이미 제외되므로 이 함수에 도달하지 않는다.
`operating_hours is None`(운영시간 미확인)이면 이 Feature 자체를 계산하지 않고
§5의 재분배 규칙을 적용한다. 미확인을 0점으로 두지 않는 이유는, 미확인이
"곧 닫음"이나 "폐점"을 의미하지 않기 때문이다(폐점과 구분되는 이유와 동일).

`environment_type` 매핑은 카테고리 기준으로 잠정 분류한다 (현재
`services/recommendations.py`의 `_INDOOR_CATEGORIES`/`_OUTDOOR_CATEGORIES`와 동일 기준):

| environment_type | category 예시 |
| --- | --- |
| `indoor` | museum, cafe, gallery, restaurant |
| `outdoor` | park, trail, beach |
| `unknown` | 그 외 |

### 4.2 날씨 적합도 (weather_fit_score)

날씨 정보가 없으면(`weather_condition is None`) 이 Feature 자체를 계산하지 않고
§5의 재분배 규칙을 적용한다. 날씨 정보가 있으면 `environment_type`과 조합한다.

| `WeatherCondition` | indoor | outdoor | unknown |
| --- | --- | --- | --- |
| `GOOD` | 0.70 | 1.00 | 0.85 |
| `NEUTRAL` | 0.80 | 0.80 | 0.80 |
| `BAD` | 1.00 | 0.30 | 0.60 |

### 4.3 거리 (distance_score)

```
distance_score = clamp(1 - distance_km / max_distance_km, 0.0, 1.0)
```

`max_distance_km`는 해당 실행의 검색 반경(`search_radius_km`)을 사용한다. 반경이
0 이하인 방어적인 경우 `distance_km == 0`이면 1.0, 아니면 0.0으로 처리한다.

### 4.4 혼잡도 (concentration_score) — A 제안 초안, D 확인 필요

> 이 절과 §5.1·§5.2의 concentration 관련 내용은 **A(Agent Runtime)가 제안하는
> 초안**이다. 이 문서의 소유자인 D가 확인하기 전까지는 미확정이며, 조사 근거와
> 배경은 [concentration-conditions.md §2.3](./concentration-conditions.md#23-scoring-반영-개요--재검토-중-1차2차-구조-d-미확인)에
> 있다.
>
> **🔶 2026-07-30 재검토 (제안, D 미확인, 최종 확정 아님)**: 아래 §4.4·§5.1·§5.2
> 본문은 "concentration이 (다른 3개 Feature와 함께) 매번 시도되고, 없으면
> `redistribute_weights()`로 재분배되는 단일 Scoring 호출" 모델을 전제로
> 쓰였다(concentration-conditions.md 안 A). 그런데 이후 성능 실측으로 "1차
> Scoring(10개, concentration 없음) → 상위 5개 → 2차 Scoring(5개+concentration)"
> 안 B가 새로 제안됐다 — 이 안에서는 **1차 Scoring엔 concentration이라는 키
> 자체가 존재하지 않는다**(결측이 아니라 "이 단계에서는 안 다룸"). 2차
> Scoring(항상 concentration 포함, 5개 한정)에서만 아래 §5.2의 개별 결측·재분배
> 로직이 의미를 갖는다. 안 A/안 B 중 어느 쪽으로 갈지 **D 확인 필요** —
> 확정 전까지 아래 본문은 안 A 기준 서술로 남겨둔다.

`concentration_intent`가 `null`/`IGNORE`면 이 Feature 자체를 계산하지 않고 §5.2의
재분배 규칙을 적용한다(날씨·남은 운영시간과 동일한 경로). `AVOID`/`SEEK`일 때만
계산하며, C의 후보 보강 응답이 반환하는 `concentration_rate`(0~100대 상대 비율,
후보별로 `no_data`/`unavailable`일 수 있음 — 그 경우도 결측으로 처리)를 사용한다.

```
concentration_score (SEEK)  = clamp(concentration_rate / 100, 0.0, 1.0)
concentration_score (AVOID) = clamp(1 - concentration_rate / 100, 0.0, 1.0)
```

선형 정규화안이다. 대안으로 `concentration_policy.py`의 4단계 구간(`quiet`/
`normal`/`slightly_crowded`/`crowded`, 임계값 20/50/70%)을 그대로 점수 구간
(예: 1.0/0.67/0.33/0.0)으로 매핑하는 방식도 있다 — 두 안 중 확정은 D와 함께
한다.

## 5. 가중치

### 5.1 기본 가중치

| Feature | 기본 가중치 |
| --- | --- |
| 날씨 | 0.40 |
| 남은 운영시간 | 0.40 |
| 거리 | 0.20 |

날씨와 남은 운영시간을 동일 비중으로 두고, 거리는 그 절반 비중으로 둔다. 카테고리는
1차 하드 필터가 처리한다고 보고 가중치 계산에서 제외한다(§1, §3).

**혼잡도 추가 시 가중치(A 제안, D 확인 필요)**: `concentration`을 `DEFAULT_WEIGHTS`에
넣고 §5.2의 기존 재분배 로직(`redistribute_weights()`)을 그대로 재사용하려면,
아래처럼 처음부터 4개 Feature로 기본값을 잡는 방법이 가장 단순하다.

| Feature | 기본 가중치 (4-Feature 안) |
| --- | --- |
| 날씨 | 0.35 |
| 남은 운영시간 | 0.35 |
| 거리 | 0.15 |
| 혼잡도 | 0.15 |

**주의**: `concentration_intent`가 `null`/`IGNORE`(다수 사용자가 여기 해당)이면
`concentration`이 결측 처리되어 §5.2 재분배를 거치는데, 그 결과는 날씨
0.4118/남은 운영시간 0.4118/거리 0.1765로 **기존 0.40/0.40/0.20과 정확히
같지 않다** (0.35/0.85, 0.35/0.85, 0.15/0.85로 재정규화되기 때문). 즉 이 안은
혼잡도에 관심 없는 대다수 실행에도 기존 기본 가중치를 미세하게 바꾼다 — 이
변화를 받아들일지, 아니면 concentration을 재분배 메커니즘 밖에서 별도 보정치로
얹는 방식(기존 3-Feature 점수에 곱연산/가산으로 반영)으로 설계를 바꿀지는 D가
확정해야 한다.

> **🔶 2026-07-30 각주(제안, D 미확인)**: 안 B(1차/2차 두 번 호출)가 채택되면
> 위 표 자체가 "1차 가중치(날씨 0.40/남은 운영시간 0.40/거리 0.20, 기존 그대로
> 무변경)"와 "2차 가중치(4-Feature, 아래 표는 그 초안)"로 완전히 나뉘어서, 위에서
> 지적한 "무관심 실행에도 기본값이 미세하게 바뀌는" 문제 자체가 사라진다 — 1차엔
> concentration이 아예 없으니 재분배가 일어날 일이 없다. 안 A/안 B 중 확정
> 전까지는 이 표를 "안 A 채택 시의 4-Feature 초안"으로 읽는다.

### 5.2 결측 시 재분배

날씨와 남은 운영시간은 각각 독립적으로 결측될 수 있다.

- 날씨: `weather_condition`이 `None`이면 해당 실행의 모든 후보에 공통으로 결측
- 남은 운영시간: 후보별 `operating_hours`가 `None`(운영시간 미확인)이면 그
  후보에만 결측
- **(A 제안, D 확인 필요) 혼잡도**: `concentration_intent`가 `null`/`IGNORE`면
  해당 실행의 모든 후보에 공통으로 결측(날씨와 동일한 패턴). `AVOID`/`SEEK`여도
  C의 후보 보강 응답이 `no_data`/`unavailable`인 후보는 그 후보에만 결측(남은
  운영시간과 동일한 패턴) — 상세는 §4.4

결측된 Feature(하나 또는 둘)를 제외하고, 그 가중치를 나머지 Feature에 **기존
비중에 비례**하여 재분배한다. 일반식은 다음과 같다.

```
remaining = {f: weight[f] for f in weights if f not in missing}
new_weight[f] = weight[f] / sum(remaining.values())   (f in remaining)
```

기본 가중치 기준 재분배 예시:

| 결측 Feature | 재분배 가중치 |
| --- | --- |
| 날씨만 결측 | 남은 운영시간 0.6667 (0.40/0.60), 거리 0.3333 (0.20/0.60) |
| 남은 운영시간만 결측 | 날씨 0.6667 (0.40/0.60), 거리 0.3333 (0.20/0.60) |
| 둘 다 결측 | 거리 1.0 |

재분배는 후보마다 다를 수 있으므로(남은 운영시간 결측이 후보별로 다름),
`weights_used`는 실행 전체가 아니라 **후보(`RankedCandidate`)마다** 노출한다
(§7 참고).

### 5.3 최종 점수

```
score = Σ (feature_score[f] * weights_used[f])   (weights_used는 후보별로 다를 수 있음)
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
    feature_scores: Mapping[str, float | None]  # 결측 Feature는 None
    weights_used: Mapping[str, float]  # 결측 Feature는 키 자체가 없음
    is_unverified: bool
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class ScoringResult:
    ranked: tuple[RankedCandidate, ...]
    excluded_place_ids: tuple[str, ...]
```

`weights_used`는 §5.2의 이유로 `ScoringResult`가 아니라 `RankedCandidate`마다
따로 노출한다 (기본 가중치를 그대로 썼는지, 어떤 Feature가 결측되어
재분배됐는지는 후보마다 다를 수 있다).

`feature_scores`는 이후 Response Generator/LLM이 추천 이유를 생성할 때 근거로 쓸 수
있도록 Feature별 점수를 그대로 노출한다 (`docs/api-contracts.md`의
`RecommendationResult.featureScores`와 동일한 의도). `reason` 문자열 자체는 Scoring
v1의 책임이 아니며 후속 업무(Response Generator)에서 `feature_scores`를 입력으로
받아 생성한다. `category`는 점수에는 반영되지 않지만 표시/설명용으로 그대로
노출한다.

## 8. 카테고리를 가중치에서 제외한 이유

1차 하드 필터가 `place_type`/`place_tag` 불일치 후보를 이미 제거한다는 전제
하에서는, 필터를 통과한 후보들이 전부 "허용된 카테고리"에 속하므로 카테고리
자체는 더 이상 변별력이 없다. 다만 아래 두 가지는 이 결정의 한계로 남는다.

- 사용자가 카테고리를 2개 이상 허용한 경우(예: "카페 아니면 공원") 그 안에서
  어느 쪽을 더 우선할지는 Scoring v1이 표현하지 못한다. 이 우선순위가 필요해지면
  Interpret/Filter 단계에서 순서를 반영하거나, Scoring에 카테고리 가중치를
  다시 추가하는 논의가 필요하다.
- 현재 저장소에는 카테고리 하드 필터 자체가 아직 구현되어 있지 않다
  (`backend/docs/provider-contract-v1.md` §10.2). 하드 필터가 실제로 붙기
  전까지는 Scoring 결과에 원하지 않는 카테고리가 섞여 나올 수 있다.

## 9. 관련 문서

- [`docs/decision-log.md`](../decision-log.md) — D-008
- [`docs/architecture.md`](../architecture.md) — Recommendation Engine 책임
- [`docs/api-contracts.md`](../api-contracts.md) — `Candidate`/`RecommendationResult` 목표 계약
- [`concentration-conditions.md`](./concentration-conditions.md) §2.3 — §4.4·§5.1·§5.2의 혼잡도 Feature 제안 배경 (A 제안, D 확인 필요)
- [INT-01: RECOMMEND](./int-01-recommend.md) — Conditions/카테고리 배경
