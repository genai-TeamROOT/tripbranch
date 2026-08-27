"""Provider/Tool이 공유하는 내부 도메인 모델.

역할: 외부 API(Naver Geocoding, KMA 단기예보, TourAPI 등) 응답을 라우터/서비스가
직접 다루지 않도록, provider 구현체가 반드시 이 타입으로 변환해서 반환하게 한다.
`ScoringCandidate`처럼 특정 provider 출력이 아니라 여러 Tool 결과가 조합되어
채워지는 Scoring 입력 모델도 이 모듈에 둔다.
이 모듈은 FastAPI/Pydantic/HTTP 라이브러리를 import하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum

from app.domain.operating_hours import OperatingSchedule


class WeatherCondition(StrEnum):
    GOOD = "good"
    NEUTRAL = "neutral"
    BAD = "bad"


@dataclass(frozen=True)
class WeatherForecastSlot:
    forecast_for: datetime
    sky_code: str | None
    precipitation_type: str | None
    temperature_celsius: float | None = None


@dataclass(frozen=True)
class WeatherForecastResult:
    latitude: float
    longitude: float
    grid_x: int
    grid_y: int
    slots: tuple[WeatherForecastSlot, ...]
    provider: str


@dataclass(frozen=True)
class OperatingHours:
    """하루 운영시간 구간 (개장~마감).

    v1은 `open_time <= close_time`인 당일 운영만 다룬다. 자정을 넘기는
    운영시간(예: 22:00~02:00)은 범위 밖이며 `TBD`다.

    `is_regular_closure`는 "이 구간은 평소 운영시간이지만 방문일은 정기 휴무"라는
    뜻이다. 휴무일에 시각을 `00:00~00:00`으로 지워 표시하던 방식을 대체한다 —
    그 표식은 폐점을 전달하는 대신 표시할 시간까지 함께 없애서, 추천 카드에
    "00:00~00:00"이 그대로 노출됐다. 시각과 휴무 여부를 한 객체에 같이 두면
    둘이 어긋난 조합이 만들어지지 않는다.
    """

    open_time: time
    close_time: time
    is_regular_closure: bool = False


@dataclass(frozen=True)
class GeocodeResult:
    query: str
    resolved_name: str
    latitude: float
    longitude: float
    candidate_count: int = 1
    administrative_district: str | None = None


@dataclass(frozen=True)
class ConcentrationForecast:
    """관광지의 날짜별 상대 집중률 예측 한 건."""

    place_name: str
    forecast_date: str | None
    concentration_rate: float | None
    raw_data: Mapping[str, object]


@dataclass(frozen=True)
class ConcentrationResult:
    """지역·관광지 조건으로 조회한 집중률 예측 결과."""

    area_code: str
    district_code: str
    requested_place_name: str | None
    forecasts: tuple[ConcentrationForecast, ...]
    provider: str


@dataclass(frozen=True)
class RealtimeCommercialCategory:
    """서울시 실시간 상권현황의 업종별 소비 활동 지표 한 건."""

    large_category: str | None
    middle_category: str | None
    activity_level: str | None


@dataclass(frozen=True)
class RealtimeCommercialResult:
    """서울시 주요 장소 한 곳의 실시간 상권현황 응답."""

    area_name: str
    area_code: str | None
    area_activity_level: str | None
    observed_at: str | None
    categories: tuple[RealtimeCommercialCategory, ...]
    provider: str


@dataclass(frozen=True)
class PopulationForecastSlot:
    """서울시 도시데이터가 제공하는 시간대별 인구 혼잡도 예측 한 건."""

    forecast_at: str
    congestion_level: str | None
    population_min: int | None
    population_max: int | None


@dataclass(frozen=True)
class RealtimePopulationResult:
    """서울시 주요 장소 단위의 현재·향후 인구 혼잡도."""

    area_name: str
    area_code: str | None
    current_congestion_level: str | None
    current_congestion_message: str | None
    observed_at: str | None
    forecast_available: bool
    forecasts: tuple[PopulationForecastSlot, ...]
    provider: str


@dataclass(frozen=True)
class RealtimeParkingLot:
    name: str
    latitude: float | None
    longitude: float | None
    capacity: int | None
    current_parked_count: int | None
    current_available: bool
    paid: bool | None
    observed_at: str | None
    # PRK_CD. 같은 주차장이 PRK_STTS에 중복으로 올 때 병합용 키로 쓴다.
    code: str | None = None
    # PRK_TYPE(NW/NS/BS/NP)을 "공영"/"민영"으로 정리한 값. 모르는 코드는 None.
    lot_type: str | None = None
    # 총면수와 현재 주차 대수를 모두 제공할 때만 계산한다. 기존 citydata는 이 값을
    # 직접 주지 않아 None이고, GetParkingInfo 경로가 결정적으로 채운다.
    available_spaces: int | None = None


@dataclass(frozen=True)
class MunicipalParkingStatus:
    """서울시 시영·공영주차장 API(GetParkingInfo)의 최신 현황 한 건.

    좌표는 API에 없으므로 ``municipal_parking_lots`` 카탈로그에서 별도로 보강한다.
    ``is_live``는 '최근 20분 안에 실시간 주차 대수가 제공됐는지'를 뜻하며, 빈자리가
    있다는 뜻이 아니다.
    """

    code: str
    name: str
    address: str | None
    district: str | None
    capacity: int | None
    current_parked_count: int | None
    observed_at: str | None
    paid: bool | None
    is_live: bool


@dataclass(frozen=True)
class StoredMunicipalParkingLot:
    """한 번 지오코딩해 Supabase에 보관하는 공영주차장 정적 카탈로그 행."""

    code: str
    name: str
    address: str | None
    district: str | None
    latitude: float | None
    longitude: float | None
    capacity: int | None
    paid: bool | None


@dataclass(frozen=True)
class RealtimeSubwayArrival:
    station_name: str
    line: str | None
    direction: str | None
    destination: str | None
    arrival_seconds: int | None
    arrival_message: str | None


@dataclass(frozen=True)
class RealtimeBusStop:
    name: str
    ars_id: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class RealtimeCityEvent:
    name: str
    period: str | None
    place: str | None
    thumbnail_url: str | None
    url: str | None


@dataclass(frozen=True)
class RoadTrafficStatus:
    """지역 인근 도로의 평균 소통 현황(citydata의 ROAD_TRAFFIC_STTS.AVG_ROAD_DATA)."""

    level: str | None
    average_speed_kmh: float | None
    message: str | None
    observed_at: str | None


@dataclass(frozen=True)
class RealtimeCityDataResult:
    """상권 활동과 인구 혼잡도를 같은 서울시 주요 장소 기준으로 묶는다."""

    commercial: RealtimeCommercialResult | None
    population: RealtimePopulationResult | None
    parking_lots: tuple[RealtimeParkingLot, ...] = ()
    subway_arrivals: tuple[RealtimeSubwayArrival, ...] = ()
    bus_stops: tuple[RealtimeBusStop, ...] = ()
    events: tuple[RealtimeCityEvent, ...] = ()
    road_traffic: RoadTrafficStatus | None = None


@dataclass(frozen=True)
class PlaceCategoryFilter:
    """TourAPI 장소 목록 조회에 사용할 선택적 분류 코드 묶음."""

    content_type_id: str | None = None
    lcls_systm1: str | None = None
    lcls_systm2: str | None = None
    lcls_systm3: str | None = None

    def __post_init__(self) -> None:
        values = (
            self.content_type_id,
            self.lcls_systm1,
            self.lcls_systm2,
            self.lcls_systm3,
        )
        if any(value is not None and not value.strip() for value in values):
            raise ValueError("분류 코드는 비어 있는 문자열일 수 없습니다.")
        if self.lcls_systm2 and not self.lcls_systm1:
            raise ValueError("lcls_systm2 사용 시 lcls_systm1이 필요합니다.")
        if self.lcls_systm3 and not (self.lcls_systm1 and self.lcls_systm2):
            raise ValueError("lcls_systm3 사용 시 lcls_systm1과 lcls_systm2가 필요합니다.")


@dataclass(frozen=True)
class PlaceDetails:
    """TourAPI의 공통·소개 상세 응답을 정규화한 장소 상세정보."""

    content_id: str
    content_type_id: str
    title: str | None
    address: str | None
    overview: str | None
    homepage: str | None
    telephone: str | None
    operating_hours: str | None
    rest_date: str | None
    raw_common: Mapping[str, object]
    raw_intro: Mapping[str, object]
    provider: str
    operating_schedule: OperatingSchedule | None = None
    # 주차·요금은 operating_hours와 같은 취급이다 — provider가 contenttypeid별 키를
    # 이미 훑어 하나로 정규화해둔다. 소비 측(info_field_rules)은 raw_intro에서
    # 원본 키를 다시 찾지 않고 이 필드를 읽는다.
    #
    # raw_intro에서 읽던 옛 경로는 남기지 않았다. 두 경로를 함께 두면 같은 질문이
    # provider에 따라 다르게 답한다.
    parking: str | None = None
    parking_fee: str | None = None
    fee: str | None = None
    baby_carriage: str | None = None
    pet: str | None = None
    credit_card: str | None = None
    restroom: str | None = None
    # 장소 카드 이미지. 캐시 경로(hybrid/supabase_place_details.py)는 원본 크기
    # firstimage(first_image_url)를 우선하고, 없으면 작은 썸네일 firstimage2로
    # 대체한다(2026-08-13) — 필드명은 thumbnail_url이지만 실제로는 대부분 원본
    # 크기 이미지가 들어온다. 실측 844건 중 169건(20%)은 이미지가 없어 None이
    # 정상 값이다 — 소비 측이 이미지 영역을 숨기는 근거다.
    thumbnail_url: str | None = None
    # 무장애 여행 정보(place_barrier_free, D-077). 무장애 목록에 등록된 장소만
    # 행이 있어 대부분의 장소에서는 전부 None이다 — 4개 구 실측 커버리지가 19%다.
    #
    # 두 가지 함정이 있다.
    #   1. wheelchair_rental_raw는 휠체어 **대여** 여부다. 휠체어로 들어갈 수 있는지가
    #      아니다. 출입 가능 여부는 approach_route_raw·entrance_access_raw가 답한다.
    #   2. approach_route_raw(접근로)와 entrance_access_raw(주출입구)는 원문에서 서로
    #      뒤바뀐 장소가 있다(가나아트센터). 한쪽만 읽어 판정하지 않는다.
    approach_route_raw: str | None = None
    entrance_access_raw: str | None = None
    elevator_raw: str | None = None
    accessible_restroom_raw: str | None = None
    accessible_parking_raw: str | None = None
    braille_block_raw: str | None = None
    braille_promotion_raw: str | None = None
    audio_guide_raw: str | None = None
    guide_dog_raw: str | None = None
    wheelchair_rental_raw: str | None = None
    stroller_rental_raw: str | None = None
    nursing_room_raw: str | None = None
    infant_family_etc_raw: str | None = None
    public_transport_raw: str | None = None
    disability_etc_raw: str | None = None


@dataclass(frozen=True)
class LocalSearchPlace:
    """Naver Local Search가 반환한 장소·업체 후보 한 건."""

    name: str
    address: str | None
    road_address: str | None
    category: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class TourPlaceRecord:
    """TourAPI 지역 기반 목록의 장소 한 건."""

    content_id: str
    content_type_id: str
    title: str
    address: str | None
    latitude: float | None
    longitude: float | None
    area_code: str
    district_code: str
    lcls_systm1: str | None
    lcls_systm2: str | None
    lcls_systm3: str | None
    source_modified_at: datetime | None
    # 목록 응답이 그대로 주는 이미지 URL(firstimage/firstimage2). 상세조회가 없어도
    # 채워지므로 detail_fetched_at이 아니라 list_fetched_at 주기를 따른다(D-056).
    first_image_url: str | None = None
    thumbnail_url: str | None = None


@dataclass(frozen=True)
class TourPlacePage:
    """TourAPI 지역 기반 목록의 페이지 메타데이터와 장소 목록."""

    page_no: int
    num_of_rows: int
    total_count: int
    places: tuple[TourPlaceRecord, ...]


@dataclass(frozen=True)
class PlaceOperatingDetails:
    """TourAPI 소개 상세 응답에서 가져온 운영시간·휴무일·주차·요금 원문."""

    content_id: str
    content_type_id: str
    operating_hours_raw: str | None
    rest_date_raw: str | None
    # 주차·요금은 운영시간과 같은 detailIntro2 응답에서 온다(D-056). 추가 호출은 없다.
    # 축제(15)에는 주차 필드가 없고, 요금 필드는 14·15·28에만 있어 대부분 None이다.
    parking_info_raw: str | None = None
    parking_fee_raw: str | None = None
    use_fee_raw: str | None = None
    discount_info_raw: str | None = None
    # 안내처 원문. 전화번호의 실제 출처는 detailCommon2의 tel이 아니라 이쪽이다 —
    # tel은 축제(15)에만 채워진다. 축제는 여기가 비고 tel이 채워진다.
    info_center_raw: str | None = None
    # 편의시설. `없음`은 빈 값과 다르다 — "없다고 답한" 것이므로 그대로 담는다.
    baby_carriage_raw: str | None = None
    pet_raw: str | None = None
    credit_card_raw: str | None = None
    restroom_raw: str | None = None


@dataclass(frozen=True)
class PlaceBarrierFreeDetails:
    """무장애 여행 정보(KorWithService2/detailWithTour2) 원문(D-077).

    detailIntro2와 다른 서비스라 호출도 따로 나간다. 응답 필드 28개 중 채움률 5%를
    넘긴 15개만 담는다(2026-08-25 실측, 4개 구 427건 기준). 담지 않는 13개는
    수어 안내·큰활자 안내물처럼 427건 중 한 자리 수만 채워진 필드들이다.

    필드 이름은 응답 키가 아니라 의미를 따른다. 응답 키를 그대로 쓰면 두 필드가
    이름과 반대로 읽힌다 — `wheelchair`는 휠체어 대여이지 출입이 아니고, `exit`는
    출구가 아니라 주출입구다.
    """

    content_id: str
    # 휠체어 접근. 접근로(route)와 출입구(exit)를 나눈 필드인데 작성자가 뒤바꿔 넣은
    # 사례가 있어, 접근 가능 여부는 두 값을 함께 읽어야 한다.
    approach_route_raw: str | None = None
    entrance_access_raw: str | None = None
    elevator_raw: str | None = None
    accessible_restroom_raw: str | None = None
    accessible_parking_raw: str | None = None
    braille_block_raw: str | None = None
    braille_promotion_raw: str | None = None
    audio_guide_raw: str | None = None
    guide_dog_raw: str | None = None
    wheelchair_rental_raw: str | None = None
    stroller_rental_raw: str | None = None
    nursing_room_raw: str | None = None
    infant_family_etc_raw: str | None = None
    public_transport_raw: str | None = None
    disability_etc_raw: str | None = None

    def has_any_value(self) -> bool:
        """값이 하나라도 있는가.

        무장애 목록에 있어도 15개가 전부 빈 장소가 496건 중 60건이다. 목록에
        있었다는 사실과 값이 있다는 사실은 다르다.
        """
        return any(
            value is not None
            for field_name, value in vars(self).items()
            if field_name != "content_id"
        )


@dataclass(frozen=True)
class PlaceCommonDetails:
    """detailCommon2에서만 얻을 수 있는 값. places 동기화 대상이 아니다.

    overview는 표본 35건 실측(2026-08-10)에서 100%(평균 326자), homepage는 63%
    채워진다. telephone(`tel`)은 축제(15)에만 있고 나머지 유형은 detailIntro2의
    안내처가 출처다 — 그쪽은 places가 캐시한다.
    """

    content_id: str
    overview: str | None
    homepage: str | None
    telephone: str | None


@dataclass(frozen=True)
class StoredPlaceLocation:
    """저장된 TourAPI 장소의 검색 중심점 해석용 최소 정보."""

    content_id: str
    title: str
    address: str | None
    latitude: float
    longitude: float
    # TourAPI 법정동 코드의 시군구 부분(lDongSignguCd, 종로구 "110"). 집중률 조회는
    # 구를 지정해야 하고 API가 그 값으로 엄격하게 거른다 - 중구 장소를 종로구로
    # 물으면 0건이 온다(D-095). 집중률 API의 signguCd는 시도까지 붙인 5자리라
    # 넘기기 전에 concentration_signgu_code()로 바꾼다.
    district_code: str | None = None
    # 집중률 응답에서 장소를 골라낼 때 대조할 정식 명칭.
    concentration_name: str | None = None
    # tAtsNm에 넣을 검색어 목록. 앞에서부터 시도하고 결과가 나오면 멈춘다(D-057).
    # 비어 있으면 concentration_name을 그대로 쓴다.
    concentration_search_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlaceEvidenceSnippet:
    """취향 근거 한 조각 — 블로그·리뷰 원문에서 뽑은 문장 하나.

    `search_place_evidence` RPC가 장소당 최대 `p_match_count`개를 유사도 내림차순
    으로 돌려준다. 같은 글에서 두 문장이 뽑히지 않도록 RPC가 url 단위로 대표
    1건만 남긴다.
    """

    source_text: str
    source_url: str | None
    similarity: float
    published_at: datetime | None


@dataclass(frozen=True)
class PlaceEvidenceMatch:
    """한 장소의 취향 근거 검색 결과.

    `avg_similarity`는 그 장소에서 살아남은 조각들의 유사도 평균이다 — 점수
    Feature의 입력 후보가 되는 값이지만, **0~1 점수로 어떻게 펼지는 아직 정하지
    않았다.** 실제 분포를 재본 뒤 정한다(계획 문서 2단계).
    """

    content_id: str
    place_title: str
    avg_similarity: float
    snippets: tuple[PlaceEvidenceSnippet, ...]


@dataclass(frozen=True)
class PlaceMoodProfile:
    """장소 사진에서 뽑은 분위기 축 점수 한 벌.

    `place_mood_vectors.axis_scores`를 그대로 담는다. 적재 때 미리 계산해 둔
    값이라 조회 경로에는 벡터 연산이 없다 — 발화에 분위기 표현이 있으면 이
    점수로 정렬만 하면 된다.

    **점수의 부호를 임계값으로 쓰지 않는다.** 특히 `세월`은 종로 631곳 중
    양수가 24곳뿐일 만큼 한쪽으로 쏠려 있어 "0보다 크면 새것"이 성립하지
    않는다. 순위는 정확하므로 정렬에만 쓴다(D-087).
    """

    content_id: str
    # 축 이름 → −1~1 점수. 키는 영문이고 부호는 `+` 쪽을 가리킨다 — calm이
    # 양수면 조용한 쪽이다. 지금 켠 축은 indoor·calm·traditional·warm_toned·
    # weathered 다섯이지만
    # 축을 켜고 끄는 일이 잦아 고정 필드로 두지 않는다.
    axis_scores: Mapping[str, float]
    # 평균에 쓴 사진 수. 1이면 detailImage2가 비어 대표 이미지 한 장으로 대체된
    # 장소이고, 그 한 장이 간판만 찍혔으면 장소가 아니라 그 사진을 대표한다.
    # 종로 631곳 중 170곳(27%)이 여기 해당한다.
    photo_count: int


@dataclass(frozen=True)
class PlaceMoodMatch:
    """사진 한 장으로 찾은 "분위기가 닮은 장소" 한 건.

    `similarity`는 올린 사진의 벡터와 장소 벡터의 코사인 유사도다. 양쪽 다
    길이 1로 정규화돼 있어 내적이 곧 유사도다.

    **얼마부터 "닮았다"인지는 아직 정하지 않았다.** 축 점수 쪽은 사람 정답표
    77곳으로 AUC를 쟀지만(D-087), 사진끼리의 유사도 컷은 표본이 없다. 재기
    전까지는 절대값이 아니라 순위만 쓴다.
    """

    content_id: str
    similarity: float
    profile: PlaceMoodProfile
    # 검색 중심에서의 거리. 반경으로 좁혀 부른 경우에만 채워진다.
    distance_km: float | None = None


@dataclass(frozen=True)
class StoredPlaceDetail:
    """요청 시 저장소에서 읽어오는 장소 상세·운영정보 한 건.

    운영시간은 정규화 결과가 아니라 TourAPI 원문(``*_raw``)을 그대로 담는다 —
    소비 시점에 normalize_operating_schedule()로 다시 정규화하므로 TourAPI를
    직접 호출하는 경로와 동일한 결과가 보장된다.
    """

    content_id: str
    content_type_id: str
    title: str | None
    address: str | None
    operating_hours_raw: str | None
    rest_date_raw: str | None
    detail_fetch_status: str
    detail_fetched_at: datetime | None
    source_modified_at: datetime | None
    # COMPARE의 TRAVEL_TIME 실측 연결(2026-08-21)이 쓴다 — A가 이 좌표로 실측 경로를
    # 조회한다. C는 좌표만 그대로 전달하고 우열은 판정하지 않는다.
    latitude: float | None = None
    longitude: float | None = None
    # 아래 필드는 추천 카드 조립(app.tools.recommendation_cards)이 쓴다. 분류 코드는
    # 카테고리 라벨을, 주차·이미지는 카드 배지와 썸네일을 채운다(D-056).
    lcls_systm1: str | None = None
    lcls_systm2: str | None = None
    lcls_systm3: str | None = None
    parking_info_raw: str | None = None
    parking_fee_raw: str | None = None
    # 이미지는 detail_fetched_at이 아니라 list_fetched_at 주기를 따른다 — 상세조회가
    # 실패한 장소에서도 채워져 있을 수 있다.
    first_image_url: str | None = None
    thumbnail_url: str | None = None
    # INFO 상세 질의가 캐시만으로 요금·전화번호·편의시설을 답하기 위한 원문.
    use_fee_raw: str | None = None
    info_center_raw: str | None = None
    baby_carriage_raw: str | None = None
    pet_raw: str | None = None
    credit_card_raw: str | None = None
    restroom_raw: str | None = None
    # 무장애 여행 정보(place_barrier_free, D-077). 무장애 목록에 등록된 장소만
    # 행이 있어 대부분의 장소에서는 전부 None이다 — 4개 구 실측 커버리지가 19%다.
    #
    # 두 가지 함정이 있다.
    #   1. wheelchair_rental_raw는 휠체어 **대여** 여부다. 휠체어로 들어갈 수 있는지가
    #      아니다. 출입 가능 여부는 approach_route_raw·entrance_access_raw가 답한다.
    #   2. approach_route_raw(접근로)와 entrance_access_raw(주출입구)는 원문에서 서로
    #      뒤바뀐 장소가 있다(가나아트센터). 한쪽만 읽어 판정하지 않는다.
    approach_route_raw: str | None = None
    entrance_access_raw: str | None = None
    elevator_raw: str | None = None
    accessible_restroom_raw: str | None = None
    accessible_parking_raw: str | None = None
    braille_block_raw: str | None = None
    braille_promotion_raw: str | None = None
    audio_guide_raw: str | None = None
    guide_dog_raw: str | None = None
    wheelchair_rental_raw: str | None = None
    stroller_rental_raw: str | None = None
    nursing_room_raw: str | None = None
    infant_family_etc_raw: str | None = None
    public_transport_raw: str | None = None
    disability_etc_raw: str | None = None


@dataclass(frozen=True)
class StoredPlaceState:
    """상세 재조회와 활성화 여부 판단에 필요한 기존 장소 상태."""

    content_id: str
    source_modified_at: datetime | None
    detail_fetched_at: datetime | None
    detail_fetch_status: str
    operating_parser_version: str
    operating_hours_raw: str | None
    rest_date_raw: str | None
    is_active: bool
    inactive_reason: str | None


@dataclass(frozen=True)
class HolidayEntry:
    """한국천문연구원 공휴일 API 응답 한 건."""

    date: str
    name: str
    kind: str | None
    sequence: int | None
    is_holiday: bool
    raw_data: Mapping[str, object]


@dataclass(frozen=True)
class HolidayResult:
    """연·월 조건으로 조회한 공휴일 결과."""

    year: int
    month: int | None
    entries: tuple[HolidayEntry, ...]
    provider: str

    @property
    def holidays(self) -> tuple[HolidayEntry, ...]:
        """응답 중 isHoliday=Y인 항목만 반환한다."""
        return tuple(entry for entry in self.entries if entry.is_holiday)


@dataclass(frozen=True)
class ScoringCandidate:
    """Scoring v1의 입력 후보 공통 모델 (Candidate Model v1).

    역할: 특정 Provider나 Tool 출력 형태에 종속되지 않는 정규화된 후보 표현.
    `PlaceCandidate`(Provider 산출물)에 Tool Context가 채워 넣은 판단 근거
    (운영 상태, 실내외 구분, 거리)를 더해 Scoring이 필요로 하는 형태로 만든
    것이다. C-01 Tool 계약이 확정되기 전에는 이 모델에 맞춘 응답 샘플/Stub
    데이터로 Scoring을 개발하고, Tool 완성 후에는 Tool 출력 → 이 모델로의
    변환만 새로 작성하면 된다.

    `category`는 표시용 메타데이터로만 보존한다 (Scoring v1은 카테고리를
    가중치 계산에 사용하지 않고, place_type/place_tag 1차 하드 필터가 이미
    처리했다고 전제한다). `operating_hours`가 `None`이면 운영시간 자체를
    확인하지 못한 상태(미검증)이고, 폐점 여부는 Scoring이 `now`와
    `operating_hours`를 비교해 최종 하드 필터로 직접 판정한다.
    """

    place_id: str
    name: str
    category: str
    environment_type: str  # "indoor" | "outdoor" | "unknown"
    distance_km: float
    operating_hours: OperatingHours | None
    raw_source: str = "unknown"
