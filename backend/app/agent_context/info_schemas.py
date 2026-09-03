"""INFO 전용 A–C 계약.

INFO 질의는 RECOMMEND Context와 입력·응답 형태가 달라 별도 모델로 둔다.
실제 Tool 호출과 근접치 fallback 여부는 C 서비스가 결정하며, A는 이 계약만 사용한다.

question_type은 두 갈래로 나뉜다(int-02-info.md §6).

- ``concentration`` — 집중률 API 경로. ConcentrationInfoResult를 돌려준다.
- ``event`` — 지역 행사 조회 경로. EventInfoResult를 돌려준다.
- ``realtime_commercial`` — 서울시 지역·업종별 실시간 상권 경로. 매장 자체가 아닌
  가까운 제공 상권의 카페 소비 활동을 RealtimeCommercialInfoResult로 돌려준다.
- 그 외 — 장소 상세 경로. PlaceInfoResult를 돌려준다.

세 결과는 채우는 필드가 전혀 겹치지 않아 하나로 합치면 대부분이 None인 모델이
된다. 소비 측(A의 response_composer)이 어느 필드를 읽어야 하는지 result의 타입만
보고 알 수 있도록 union으로 둔다.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.agent_context.schemas import Clarification, ContextError, Coordinates, ResponseMetadata
from app.schemas import StaleAreaProbeDebug

# int-02-info.md §6의 QuestionType. A의 app.schemas.QuestionType과 값이 일치해야
# 한다 — A가 InfoPayload.question_type.value를 그대로 실어 보낸다.
InfoQuestionType = Literal[
    "operating_hours",
    "fee",
    "parking",
    "facility",
    "event",
    "location_info",
    "general_info",
    "concentration",
    "realtime_commercial",
    "realtime_parking",
    "realtime_public_parking",
    "realtime_subway",
    "realtime_bus",
    "realtime_event",
    "realtime_traffic",
]


class InfoContextRequest(BaseModel):
    """A가 C에 보내는 단일 장소 INFO 질의 요청."""

    request_id: str = Field(min_length=1)
    intent: Literal["INFO"] = "INFO"
    place_name: str | None = None
    place_context: Literal["explicit", "from_recommendation", "from_conversation"]
    # 기존 호출부(집중률 전용)와의 호환을 위해 기본값을 유지한다.
    question_type: InfoQuestionType = "concentration"
    # 사용자 원문 질문. C는 판정에 쓰지 않고 응답 조립 참고용으로 실어 보낸다.
    specific_question: str | None = None
    visit_time: str | None = None

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("request_id는 공백일 수 없습니다.")
        return normalized

    @field_validator("place_name", "specific_question")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("visit_time")
    @classmethod
    def validate_visit_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return date.fromisoformat(normalized).isoformat()
        except ValueError as exc:
            raise ValueError("visit_time은 YYYY-MM-DD 형식이어야 합니다.") from exc


class ConcentrationInfoResult(BaseModel):
    """C가 반환하는 혼잡도 조회 결과 한 건."""

    status: Literal["success", "no_data", "unavailable"]
    is_proxy: bool = False
    requested_place_name: str | None = None
    resolved_place_name: str | None = None
    forecast_date: str | None = None
    concentration_rate: float | None = Field(default=None, ge=0)
    concentration_level: Literal["quiet", "normal", "slightly_crowded", "crowded"] | None = None
    concentration_label: str | None = None
    forecasts: list[ConcentrationForecastInfo] = Field(default_factory=list)
    error: ContextError | None = None


class ConcentrationForecastInfo(BaseModel):
    """관광지 집중률의 일 단위 예측 막대 한 건."""

    forecast_date: str
    concentration_rate: float = Field(ge=0)
    concentration_level: Literal["quiet", "normal", "slightly_crowded", "crowded"]
    concentration_label: str


class RealtimeInfoDetailItem(BaseModel):
    """서울시 실시간 INFO 상세 카드의 추가 항목 한 건.

    도시데이터는 관광지 ``PlaceDetails``와 다른 지역 단위 데이터다. 따라서
    ``fields``(말풍선 아래 요약)와 별도로 이 모델에 세부 목록·이미지·외부 링크를
    보존해 모달에서 같은 요약만 반복하지 않게 한다.
    """

    title: str
    subtitle: str | None = None
    details: dict[str, str] = Field(default_factory=dict)
    thumbnail_url: str | None = None
    external_url: str | None = None


class RealtimeCommercialInfoResult(BaseModel):
    """서울시 실시간 상권현황을 지역·업종 기준으로 정규화한 결과.

    API는 개별 매장 단위 데이터를 제공하지 않는다. ``is_proxy``는 항상 True이며,
    매장 좌표에서 가까운 서울시 제공 상권의 카드 소비 활동을 대체 근거로 쓴다.
    """

    status: Literal["success", "no_data", "unavailable"]
    is_proxy: bool = True
    requested_place_name: str | None = None
    resolved_place_name: str | None = None
    area_name: str | None = None
    area_code: str | None = None
    proxy_distance_km: float | None = Field(default=None, ge=0)
    category_label: str | None = None
    commercial_level: str | None = None
    commercial_scope: Literal["cafe_category", "area_overall"] | None = None
    observed_at: str | None = None
    population_current_level: str | None = None
    population_observed_at: str | None = None
    population_forecasts: list[PopulationForecastInfo] = Field(default_factory=list)
    detail_items: list[RealtimeInfoDetailItem] = Field(default_factory=list)
    source_url: str | None = None
    error: ContextError | None = None


class RealtimePopulationInfoResult(BaseModel):
    """가까운 서울시 제공 지역의 실시간 인구 혼잡도 결과.

    서울시 도시데이터는 개별 관광지·역의 값이 아니라 정해진 지역 단위 값이다.
    따라서 요청 위치와 제공 지역이 다를 수 있음을 ``is_proxy``와 거리로 명시한다.
    """

    status: Literal["success", "no_data", "unavailable"]
    is_proxy: bool = True
    requested_place_name: str | None = None
    resolved_place_name: str | None = None
    area_name: str | None = None
    area_code: str | None = None
    proxy_distance_km: float | None = Field(default=None, ge=0)
    current_congestion_level: str | None = None
    current_congestion_message: str | None = None
    observed_at: str | None = None
    population_forecasts: list[PopulationForecastInfo] = Field(default_factory=list)
    source_url: str | None = None
    map_url: str | None = None
    error: ContextError | None = None
    # 우리 121곳 목록엔 없지만 서울시 API는 지원하는 지역을 찾았을 때만 채워진다
    # (TP-141/D-084). 응답 판정(area_name 등)에는 영향을 주지 않는다 — 감사
    # 화면 배너용 신호일 뿐이다.
    stale_area_detected: StaleAreaProbeDebug | None = None


class RealtimeCityInfoResult(BaseModel):
    """서울시 도시데이터의 주차·대중교통·행사 결과를 공통 카드 계약으로 전달한다."""

    status: Literal["success", "no_data", "unavailable"]
    question_type: Literal[
        "realtime_parking",
        "realtime_public_parking",
        "realtime_subway",
        "realtime_bus",
        "realtime_event",
        "realtime_traffic",
    ]
    requested_place_name: str | None = None
    resolved_place_name: str | None = None
    area_name: str | None = None
    observed_at: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    detail_items: list[RealtimeInfoDetailItem] = Field(default_factory=list)
    source_url: str | None = None
    # realtime_traffic만 채운다(2026-09-02 실사용 요청) — 인구 혼잡도 카드가 쓰는
    # 서울시 실시간 도시데이터 지도 미리보기와 같은 링크다. 도로소통은 핫스팟
    # 지역 하나에 대응하는 단일 스냅샷이라 지도로 위치를 바로 확인하고 싶어한다.
    map_url: str | None = None
    error: ContextError | None = None


class PopulationForecastInfo(BaseModel):
    forecast_at: str
    congestion_level: str | None = None
    population_min: int | None = Field(default=None, ge=0)
    population_max: int | None = Field(default=None, ge=0)


class PlacePhotoItem(BaseModel):
    """상세 화면에 보여줄 장소 사진 한 장.

    순서는 목록의 순서가 그대로 뜻을 갖는다 — TourAPI가 대표성 높은 사진을 앞에
    주므로 첫 번째가 가장 대표적이다. photo_order 값을 그대로 싣지 않는 이유는
    소비 측이 그 숫자로 할 일이 없기 때문이다(빠진 번호도 없다).

    image_name은 "중구_남대문 종합상가 (5)"처럼 원본 파일명이다. 화면에 그대로
    쓰기에는 거칠어 지금은 대체 텍스트 후보로만 나른다.
    """

    url: str
    image_name: str | None = None


class PlaceCard(BaseModel):
    """장소 상세 카드가 펼쳐질 때 표시할 전체 묶음.

    ``fields``와 목적이 다르다. ``fields``는 "물어본 질문에 답이 있었나"를 나타내고
    (그래서 status 판정의 근거다), 이 모델은 "그 장소에 대해 보여줄 수 있는 것
    전부"다. 질문 유형과 무관하게 같은 모양으로 채운다.

    두 값을 합치지 않는 이유: ``fields``에 전부 담으면 overview가 거의 항상 있어
    빈 dict가 나오지 않고, 그러면 "주차 정보는 없어요" 같은 안내의 근거가 사라진다.

    값이 없는 항목은 None이다 — 빈 문자열이나 "정보 없음" 문구를 C가 지어내지
    않는다. 소비 측이 None인 항목을 숨긴다.

    편의시설은 하나로 합치지 않고 네 항목을 그대로 둔다. 합치면 어느 항목이 빠졌는지
    구분되지 않고, ``없음``처럼 "없다고 답한" 값과 "정보가 없는" 값도 섞인다.
    """

    place_id: str | None = None
    place_name: str | None = None
    # 실측 844건 중 169건(20%)은 이미지가 없다. 소비 측은 이미지 영역을 숨긴다.
    thumbnail_url: str | None = None
    # 여러 장 보기용 사진 목록. 출처가 thumbnail_url과 다르다 — 이쪽은
    # place_image_embeddings에 적재된 detailImage2 사진이고, thumbnail_url은
    # places 행의 대표 이미지다.
    #
    # **thumbnail_url을 대체하지 않는다.** 사진이 있는 5,465곳 중 3,074곳이 한
    # 장뿐이고 전체 8,060곳 중 2,595곳은 아예 없다(2026-08-31 실측). 목록이 비어도
    # 대표 이미지는 있는 장소가 대부분이라, 목록만 보고 그리면 지금 보이던 사진이
    # 사라진다.
    photos: list[PlacePhotoItem] = Field(default_factory=list)
    overview: str | None = None
    operating_hours: str | None = None
    rest_date: str | None = None
    parking: str | None = None
    parking_fee: str | None = None
    fee: str | None = None
    baby_carriage: str | None = None
    pet: str | None = None
    credit_card: str | None = None
    restroom: str | None = None
    homepage: str | None = None


class PlaceInfoResult(BaseModel):
    """C가 반환하는 장소 상세 조회 결과 한 건(concentration 외 question_type).

    ``fields``는 question_type별로 C가 채우는 정규화된 키-값이다. TourAPI의
    detailIntro2는 contentTypeId마다 필드명이 달라(``usetime``/``usetimeculture``/
    ``opentime`` …) 유형별 전용 모델을 두면 소비 측이 8가지 모양을 모두 알아야
    한다. C가 키 이름을 고정해 넘기고(INFO_FIELD_KEYS), A는 키만 보고 렌더한다.

    값이 하나도 없으면 status="no_data"이고 fields는 빈 dict다 — 빈 문자열이나
    "정보 없음" 같은 문구를 C가 지어내지 않는다.

    ``place_card``는 그 판정과 무관하게 채운다. 챗봇 말풍선은 ``fields``로 쓰고
    (그래서 "주차 정보는 없어요"가 정확히 나가고), 그 아래 펼쳐지는 카드는
    ``place_card``로 그린다.
    """

    status: Literal["success", "no_data", "unavailable"]
    question_type: InfoQuestionType
    requested_place_name: str | None = None
    resolved_place_name: str | None = None
    place_id: str | None = None
    # A가 현재 위치→목적지의 도보 경로를 한 건 조회할 때만 사용한다. 주소만 묻는
    # location_info에는 추가 호출을 만들지 않으며, 화면 카드에도 노출하지 않는다.
    destination_coordinates: Coordinates | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    # 상세 조회를 하지 않는 경로(location_info 등)에서는 None이다.
    place_card: PlaceCard | None = None
    error: ContextError | None = None


class EventItem(BaseModel):
    """진행 중인 행사 한 건."""

    title: str
    start_date: str
    end_date: str
    address: str | None = None
    distance_km: float | None = Field(default=None, ge=0)
    # 행사 제목에 대상 장소명이 들어 있는 경우(예: "경복궁 별빛야행"). False면 그
    # 장소의 행사가 아니라 근처에서 열리는 행사다 — A는 이 구분을 반드시 문구에
    # 반영해야 한다(집중률 is_proxy와 같은 취지).
    is_direct_match: bool = False
    image_url: str | None = None


class EventInfoResult(BaseModel):
    """C가 반환하는 INFO 행사 질의 결과(question_type=event).

    TourAPI에는 장소별 행사 조회가 없어 지역(종로구) 단위로 받아 좌표로 거리를
    매긴다. 그래서 events 대부분은 대상 장소 "근처"의 행사다 — 요청한 장소에서
    열리는 행사인 것처럼 말하지 않도록 is_direct_match와 distance_km을 함께
    내려준다.
    """

    status: Literal["success", "no_data", "unavailable"]
    question_type: Literal["event"] = "event"
    requested_place_name: str | None = None
    resolved_place_name: str | None = None
    reference_date: str | None = None
    events: list[EventItem] = Field(default_factory=list)
    has_direct_match: bool = False
    error: ContextError | None = None


class InfoContextResponse(BaseModel):
    """C가 반환하는 INFO 질의 응답."""

    request_id: str
    intent: Literal["INFO"] = "INFO"
    contract_version: Literal["draft-v0"] = "draft-v0"
    status: Literal["success", "no_data", "needs_clarification", "unsupported", "unavailable"]
    result: (
        ConcentrationInfoResult
        | RealtimeCommercialInfoResult
        | RealtimePopulationInfoResult
        | RealtimeCityInfoResult
        | PlaceInfoResult
        | EventInfoResult
        | None
    ) = None
    clarification: Clarification | None = None
    error: ContextError | None = None
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)


__all__ = [
    "ConcentrationInfoResult",
    "EventInfoResult",
    "EventItem",
    "InfoContextRequest",
    "InfoContextResponse",
    "InfoQuestionType",
    "PlaceCard",
    "PlaceInfoResult",
    "RealtimeCommercialInfoResult",
    "RealtimePopulationInfoResult",
    "RealtimeCityInfoResult",
]
