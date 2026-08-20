"""위치 기반 장소 수집과 거리 계산이 공유하는 정책 상수."""

from app.domain.travel_route import TravelMode

# 성인의 MVP 도보 이동속도 가정값(km/분): 1분에 약 70m를 이동한다.
WALKING_SPEED_KM_PER_MINUTE = 0.07

# 도보가 아닌 이동수단의 MVP 이동속도 가정값(km/분) = 20km/h.
#
# **이 값은 실측 속도가 아니라 검색 반경을 만든 가정과 같은 값이어야 한다.**
# 반경 산정(runtime/recommendation_transform.py::to_search_radius_km)이 비도보
# 요청에 20km/h를 쓰므로, 시간 예산이 같은 값으로 나눠야 사용자가 말한 이동시간이
# 그대로 예산이 된다(scoring.py::_travel_minutes_budget 참고). 실측값을 넣으면
# 분모가 "사용자 약속"이 아니게 되어 그 설계가 깨진다.
#
# 같은 20km/h가 recommendation_transform._OTHER_KM_PER_MIN에도 있다. 두 값은
# 반드시 같아야 하므로 한쪽만 바꾸지 않는다. 파일이 A·C로 갈려 있어 아직 상수를
# 합치지 못했다.
NON_WALKING_SPEED_KM_PER_MINUTE = 20 / 60

# 이동수단별 이동속도 가정값(km/분). 거리 점수의 시간 예산이 이 값으로 검색
# 반경을 소요시간으로 되돌린다(domain/scoring.py::_travel_minutes_budget).
#
# 대중교통도 20km/h를 쓴다. 실측값(경복궁 기준 7개 구간에서 직선거리 기준 실효
# 4.6~19km/h)이 아니라 반경 산정과 같은 가정이어야 하기 때문이다 — 반경 산정
# (recommendation_transform.to_search_radius_km)이 비도보 요청을 이동수단으로
# 가르지 않고 _OTHER_KM_PER_MIN 하나로 처리한다. 여기에 실측을 넣으면 분자와
# 분모의 기준이 어긋난다.
#
# 새 이동수단을 넣을 때 함께 넓혀야 하는 곳이 하나 더 있다: scoring.py의
# _applied_travel_route()가 실측 여부를 RouteSource로 가리므로 새 이동수단의
# source도 허용해야 한다. 둘 중 하나만 바꾸면 채점이 속도를 못 찾아 KeyError로
# 멈춘다 — 조용히 도보 속도로 재는 것보다 이 편이 낫다.
#
# 자동차 가정(20km/h)과 실제의 차이(네이버 Directions 실 API, 경복궁 기준 종로
# 6개 지점, 2026-08-20 14시대 평일):
#
# - 우회 계수 평균 **1.31배**(직선 대비 실제 도로 경로), 범위 1.07~1.71
# - 도로 기준 실주행 속도 평균 **6.98km/h**, 범위 4.64~8.79
# - 직선거리 기준 실효 속도는 평균 **5.38km/h**(범위 3.47~6.68)로, 이 가정
#   20km/h의 **약 1/3.7**이다. 도심 정체 때문이며 도보 실효 2.31km/h와 비교하면
#   자동차가 도보보다 2.3배 빠른 정도에 그친다.
# - 그래서 거리 점수는 도보보다 더 쉽게 0이 된다. 도보와 같은 이유로 보정하지
#   않는다 — 사용자가 "30분"이라고 했으면 예산도 30분이어야 한다.
# - 표본이 종로 6개 지점·특정 시간대뿐이다. 시간대에 따라 크게 달라지므로 이
#   숫자로 반경 가정을 바꾸기 전에 표본을 넓혀야 한다.
TRAVEL_SPEED_KM_PER_MINUTE: dict[TravelMode, float] = {
    TravelMode.WALKING: WALKING_SPEED_KM_PER_MINUTE,
    TravelMode.DRIVING: NON_WALKING_SPEED_KM_PER_MINUTE,
    TravelMode.TRANSIT: NON_WALKING_SPEED_KM_PER_MINUTE,
}

# 이동시간 조건이 없을 때 A와 C가 공통으로 사용하는 기본 장소 검색 반경(km).
DEFAULT_PLACE_SEARCH_RADIUS_KM = 2.0

# 짧은 이동시간도 후보 수집이 가능하도록 보장하는 최소 장소 검색 반경(km).
MIN_PLACE_SEARCH_RADIUS_KM = 0.3

# 장소 검색 Tool과 Provider가 허용하는 최대 검색 반경(km).
MAX_PLACE_SEARCH_RADIUS_KM = 20.0

# TourAPI 법정동 코드 기준 MVP 장소 검색 지원 지역: 서울특별시 종로구.
# 집중률 API의 signguCd(종로구 11110)와 다른 코드 체계이므로 혼용하지 않는다.
PLACE_SEARCH_LDONG_REGION_CODE = "11"
PLACE_SEARCH_LDONG_DISTRICT_CODE = "110"

# 별도 조회 개수가 없을 때 Place Provider가 반환할 기본 최대 건수.
DEFAULT_PLACE_PROVIDER_RESULT_LIMIT = 20

# 두 위·경도 사이의 직선거리를 Haversine 공식으로 계산할 때 사용하는 지구 반지름(km).
EARTH_RADIUS_KM = 6371.0
