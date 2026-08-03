"""위치 기반 장소 수집과 거리 계산이 공유하는 정책 상수."""

# 성인의 MVP 도보 이동속도 가정값(km/분): 1분에 약 70m를 이동한다.
WALKING_SPEED_KM_PER_MINUTE = 0.07

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
