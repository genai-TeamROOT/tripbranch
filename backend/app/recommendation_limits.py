"""추천 파이프라인과 Context 수집이 공유하는 후보 개수 정책."""

# 추천 결과와 후보 수집 요청에서 허용하는 최소 건수.
MIN_RECOMMENDATION_LIMIT = 1

# 추천 파이프라인이 한 번에 수집·보강하도록 허용하는 절대 후보 상한.
MAX_RECOMMENDATION_CANDIDATE_LIMIT = 20

# 사용자에게 최종 반환할 추천 장소의 기본 개수.
DEFAULT_RECOMMENDATION_RESULT_LIMIT = 5

# 점수 계산 전에 C가 수집할 추천 후보의 기본 개수.
#
# 노출 개수(RECOMMEND 5 / SCHEDULE 10)와의 차이가 여유분이다 — D가 영업 종료 후보를
# 하드 필터로 떨어뜨리므로(domain/scoring.py::_is_closed) 여유분이 없으면 카드가 다
# 안 채워진다. 종로구 실측으로 14시엔 반경 2km 후보의 2.7%, 21시엔 55.6%가 영업
# 종료라 밤일수록 여유분이 부족해진다. 실제로 모자라는 게 관측되면 그때 올린다
# (상한은 MAX_RECOMMENDATION_CANDIDATE_LIMIT).
DEFAULT_RECOMMENDATION_CANDIDATE_LIMIT = 10
