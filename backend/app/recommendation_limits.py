"""추천 파이프라인과 Context 수집이 공유하는 후보 개수 정책."""

# 추천 결과와 후보 수집 요청에서 허용하는 최소 건수.
MIN_RECOMMENDATION_LIMIT = 1

# 추천 파이프라인이 한 번에 수집·보강하도록 허용하는 절대 후보 상한.
MAX_RECOMMENDATION_CANDIDATE_LIMIT = 20

# 사용자에게 최종 반환할 추천 장소의 기본 개수.
DEFAULT_RECOMMENDATION_RESULT_LIMIT = 5

# 점수 계산 전에 C가 수집할 추천 후보의 기본 개수.
DEFAULT_RECOMMENDATION_CANDIDATE_LIMIT = 10
