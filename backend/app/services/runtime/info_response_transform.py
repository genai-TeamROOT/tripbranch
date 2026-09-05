"""C의 INFO 장소 카드 묶음을 A의 최종 응답 계약으로 변환한다."""

from __future__ import annotations

from app.agent_context.info_schemas import (
    ConcentrationInfoResult,
    EventInfoResult,
    InfoContextResponse,
    PlaceCard,
    PlaceInfoResult,
    PopulationAgeShareInfo,
    PopulationForecastInfo,
    RealtimeCityInfoResult,
    RealtimeCommercialInfoResult,
    RealtimePopulationInfoResult,
    SeoulRealtimeSummaryInfo,
)
from app.agent_context.info_schemas import (
    RealtimeInfoDetailItem as ContextRealtimeInfoDetailItem,
)
from app.schemas import (
    ConcentrationForecastBar,
    InfoPlaceCard,
    PlacePhotoItem,
    PopulationForecastBar,
    QuestionType,
    RealtimeInfoDetailItem,
    SeoulRealtimePaymentCategory,
    SeoulRealtimeSummary,
)
from app.services.runtime.info_display import (
    format_citydata_timestamp,
    format_parking_for_display,
    parse_citydata_timestamp,
)

# 서울시 원문 그대로의 인구 혼잡도 단계 — 값이 늘어나지 않는 한 이 4단계다
# (프론트 CONGESTION_HEIGHT와 순서를 맞춘다).
_CONGESTION_LEVEL_RANK = {"여유": 0, "보통": 1, "약간 붐빔": 2, "붐빔": 3}


def _peak_forecast(
    observed_at: str | None, forecasts: list[PopulationForecastInfo]
) -> tuple[PopulationForecastInfo, int] | None:
    """향후 예측 중 가장 붐비는 슬롯과 몇 시간 뒤인지를 고른다.

    과거 추이는 서울시 API가 애초에 제공하지 않아(미래 방향만 응답) 다루지
    않는다. 관측 시각과 예측 시각을 둘 다 실제 파싱해 시간 차를 구한다 —
    슬롯 간격이 항상 정확히 1시간이라고 가정하지 않는다.
    """

    observed = parse_citydata_timestamp(observed_at)
    if observed is None:
        return None

    ranked = [
        (forecast, _CONGESTION_LEVEL_RANK.get(forecast.congestion_level or "", -1))
        for forecast in forecasts
    ]
    ranked = [(forecast, rank) for forecast, rank in ranked if rank >= 0]
    if not ranked:
        return None
    if len({rank for _, rank in ranked}) == 1:
        # 전부 같은 단계면 "가장 붐빈다"고 짚어줄 시간대가 없다.
        return None

    # 최고 단계 중 가장 이른 시각을 고른다.
    best_forecast = None
    best_rank = -1
    best_hours_ahead = None
    for forecast, rank in ranked:
        peak_at = parse_citydata_timestamp(forecast.forecast_at)
        if peak_at is None:
            continue
        hours_ahead = round((peak_at - observed).total_seconds() / 3600)
        is_better = rank > best_rank or (
            rank == best_rank and best_hours_ahead is not None and hours_ahead < best_hours_ahead
        )
        if best_forecast is None or is_better:
            best_forecast, best_rank, best_hours_ahead = forecast, rank, hours_ahead
    if best_forecast is None or best_hours_ahead is None or best_hours_ahead <= 0:
        return None
    if parse_citydata_timestamp(best_forecast.forecast_at) is None:
        return None
    return best_forecast, best_hours_ahead


def _summarize_population_peak(
    observed_at: str | None, forecasts: list[PopulationForecastInfo]
) -> str | None:
    """가장 붐빌 시간대를 카드에 실을 한 줄 요약으로 만든다."""

    peak = _peak_forecast(observed_at, forecasts)
    if peak is None:
        return None
    best_forecast, best_hours_ahead = peak
    peak_at = parse_citydata_timestamp(best_forecast.forecast_at)
    if peak_at is None:
        return None
    level = best_forecast.congestion_level or "알 수 없음"
    return (
        f"{peak_at.hour}시({best_hours_ahead}시간 후)에 가장 붐빌 것으로 예상돼요. "
        f"혼잡정도는 {level}일 것으로 예상돼요."
    )


def _peak_forecast_hour_label(
    observed_at: str | None, forecasts: list[PopulationForecastInfo]
) -> tuple[str, str | None] | None:
    """가장 붐빌 시간대를 "오후 5시" 꼴 짧은 라벨과 그때의 단계로 돌려준다.

    서울시 앱의 "오늘의 인기 시간대"와 달리 이건 과거를 포함한 하루 통계가
    아니라 앞으로의 예측이다 — 원본이 미래 12시간만 주기 때문이다(D-090).
    """

    peak = _peak_forecast(observed_at, forecasts)
    if peak is None:
        return None
    best_forecast, _ = peak
    peak_at = parse_citydata_timestamp(best_forecast.forecast_at)
    if peak_at is None:
        return None
    meridiem = "오전" if peak_at.hour < 12 else "오후"
    return f"{meridiem} {peak_at.hour % 12 or 12}시", best_forecast.congestion_level


def _top_age_share(shares: list[PopulationAgeShareInfo]) -> PopulationAgeShareInfo | None:
    """비율이 가장 높은 연령대 한 건. 동률이면 어린 연령대가 이긴다(응답 순서)."""

    return max(shares, key=lambda share: share.rate, default=None)


def _is_not_busier_than_now(peak_level: str | None, current_level: str | None) -> bool:
    """예측 피크가 현재보다 더 붐비지 않는지 본다.

    두 단계 중 하나라도 우리가 모르는 값이면 판단하지 않고 False를 돌려준다 —
    모르는 단계 때문에 있는 정보를 감추지 않는다.
    """

    peak_rank = _CONGESTION_LEVEL_RANK.get(peak_level or "")
    current_rank = _CONGESTION_LEVEL_RANK.get(current_level or "")
    if peak_rank is None or current_rank is None:
        return False
    return peak_rank <= current_rank


def _to_seoul_realtime_summary(
    summary: SeoulRealtimeSummaryInfo | None,
    *,
    observed_at: str | None,
    forecasts: list[PopulationForecastInfo],
    current_level: str | None,
) -> SeoulRealtimeSummary | None:
    """C의 실시간 요약을 카드 계약으로 옮기고, 표시용 라벨만 여기서 만든다."""

    if summary is None:
        return None
    peak = _peak_forecast_hour_label(observed_at, forecasts)
    if peak is not None and _is_not_busier_than_now(peak[1], current_level):
        # 지금이 이미 예측 피크만큼 붐비면 "가장 붐빌 시간대"라고 짚을 시각이
        # 없다. 그대로 두면 강남역처럼 현재 붐빔·예측 최고 약간 붐빔인 지역에서
        # 지금보다 덜 붐비는 시각을 피크로 보여준다(2026-09-05 실측).
        peak = None
    top_age = _top_age_share(summary.age_shares)
    return SeoulRealtimeSummary(
        population_min=summary.population_min,
        population_max=summary.population_max,
        peak_forecast_hour_label=peak[0] if peak is not None else None,
        peak_forecast_level=peak[1] if peak is not None else None,
        top_age_label=top_age.label if top_age is not None else None,
        top_age_rate=top_age.rate if top_age is not None else None,
        commercial_level=summary.commercial_level,
        commercial_observed_at=format_citydata_timestamp(summary.commercial_observed_at),
        payment_count=summary.payment_count,
        payment_amount_min=summary.payment_amount_min,
        payment_amount_max=summary.payment_amount_max,
        top_payment_categories=[
            SeoulRealtimePaymentCategory(
                label=category.label,
                activity_level=category.activity_level,
                payment_count=category.payment_count,
                payment_amount_min=category.payment_amount_min,
                payment_amount_max=category.payment_amount_max,
            )
            for category in summary.top_payment_categories
        ],
    )


def to_info_place_card(response: InfoContextResponse) -> InfoPlaceCard | None:
    """장소가 확인된 모든 INFO 결과를 카드 묶음으로 AgentResponse에 전달한다.

    C의 ``location_info``·혼잡도·행사 경로는 비용을 아끼기 위해 PlaceDetails를
    조회하지 않아 ``place_card``가 비어 있을 수 있다. 이 경우에도 사용자가 INFO
    답변 아래에서 같은 장소 맥락을 확인할 수 있도록, C가 이미 확정한 장소명과
    답변 사실만으로 최소 카드를 만든다. Overview·썸네일 같은 상세는 C가 제공한
    경우에만 채운다.
    """

    result = response.result
    if isinstance(result, PlaceInfoResult):
        return _to_place_info_card(result)
    if isinstance(result, ConcentrationInfoResult):
        return _to_concentration_card(result)
    if isinstance(result, EventInfoResult):
        return _to_event_card(result)
    if isinstance(result, RealtimeCommercialInfoResult):
        return _to_realtime_commercial_card(result)
    if isinstance(result, RealtimePopulationInfoResult):
        return _to_realtime_population_card(result)
    if isinstance(result, RealtimeCityInfoResult):
        return InfoPlaceCard(
            question_type=QuestionType(result.question_type),
            answer_fields=result.fields,
            place_name=result.resolved_place_name or result.requested_place_name,
            realtime_area_name=result.area_name,
            realtime_observed_at=format_citydata_timestamp(result.observed_at),
            realtime_source_url=result.source_url,
            realtime_map_url=result.map_url,
            realtime_detail_items=_to_realtime_detail_items(result.detail_items),
        )
    return None


def _to_place_info_card(result: PlaceInfoResult) -> InfoPlaceCard:
    """상세 조회 유무와 관계없이 장소 정보 INFO 카드를 만든다."""

    card = result.place_card or PlaceCard(
        place_id=result.place_id,
        place_name=result.resolved_place_name or result.requested_place_name,
    )
    return InfoPlaceCard(
        question_type=QuestionType(result.question_type),
        answer_fields={
            key: format_parking_for_display(value) if key == "parking" else value
            for key, value in result.fields.items()
        },
        place_id=card.place_id,
        place_name=card.place_name,
        latitude=(
            result.destination_coordinates.latitude
            if result.destination_coordinates
            else None
        ),
        longitude=(
            result.destination_coordinates.longitude
            if result.destination_coordinates
            else None
        ),
        thumbnail_url=card.thumbnail_url,
        photos=[
            PlacePhotoItem(url=photo.url, image_name=photo.image_name)
            for photo in card.photos
        ],
        overview=card.overview,
        operating_hours=card.operating_hours,
        rest_date=card.rest_date,
        parking=format_parking_for_display(card.parking),
        parking_fee=card.parking_fee,
        fee=card.fee,
        baby_carriage=card.baby_carriage,
        pet=card.pet,
        credit_card=card.credit_card,
        restroom=card.restroom,
        homepage=card.homepage,
        # 무장애 아홉 항목(D-077). C가 이미 원문 정리·합성을 끝낸 값이라 여기서는
        # 그대로 옮기기만 한다 — 손대면 같은 원문이 답변과 카드에서 갈린다.
        accessible_restroom=card.accessible_restroom,
        accessible_parking=card.accessible_parking,
        elevator=card.elevator,
        visual_guide=card.visual_guide,
        wheelchair_rental=card.wheelchair_rental,
        nursing_room=card.nursing_room,
        seating=card.seating,
        stroller_rental=card.stroller_rental,
        guide_dog=card.guide_dog,
    )


def _to_concentration_card(result: ConcentrationInfoResult) -> InfoPlaceCard | None:
    """혼잡도 결과도 장소가 확인됐을 때 최소 카드로 보여준다."""

    place_name = result.requested_place_name or result.resolved_place_name
    if place_name is None:
        return None

    value_parts = [part for part in (result.forecast_date, result.concentration_label) if part]
    return InfoPlaceCard(
        question_type=QuestionType.CONCENTRATION,
        answer_fields={"concentration": " · ".join(value_parts)} if value_parts else {},
        place_name=place_name,
        concentration_forecasts=[
            ConcentrationForecastBar(
                forecast_date=forecast.forecast_date,
                concentration_rate=forecast.concentration_rate,
                concentration_level=forecast.concentration_level,
                concentration_label=forecast.concentration_label,
            )
            for forecast in result.forecasts
        ],
    )


def _to_event_card(result: EventInfoResult) -> InfoPlaceCard | None:
    """행사 INFO도 확정된 장소명을 중심으로 최소 카드를 보여준다.

    realtime_event 카드와 같은 가로 스크롤 사진 카드로 그리도록, event 항목도
    realtime_detail_items(제목/부제/썸네일) 모양으로 옮긴다 — 프론트가 이미
    그 모양으로 PlaceCardRow를 그리는 컴포넌트를 갖고 있다.
    """

    place_name = result.resolved_place_name or result.requested_place_name
    if place_name is None:
        return None

    event_lines = [
        f"{event.title} ({event.start_date}~{event.end_date})" for event in result.events
    ]
    return InfoPlaceCard(
        question_type=QuestionType.EVENT,
        answer_fields={"event": "\n".join(event_lines)} if event_lines else {},
        place_name=place_name,
        realtime_detail_items=[
            RealtimeInfoDetailItem(
                title=event.title,
                subtitle=f"{event.start_date}~{event.end_date}",
                thumbnail_url=event.image_url,
            )
            for event in result.events
        ],
    )


def _to_realtime_commercial_card(
    result: RealtimeCommercialInfoResult,
) -> InfoPlaceCard | None:
    """개별 매장 대신 조회한 지역·업종 상권 활동을 최소 INFO 카드로 보인다."""

    place_name = result.resolved_place_name or result.requested_place_name
    if place_name is None:
        return None

    scope_label = (
        "요청 업종"
        if result.commercial_scope != "area_overall"
        else "지역 전체 상권 (요청 업종 세부값 미제공)"
    )
    fields = {
        key: value
        for key, value in {
            "상권 지역": result.area_name,
            "상권 기준": scope_label,
            "업종": result.category_label,
            "실시간 활동": result.commercial_level,
            "기준 시각": format_citydata_timestamp(result.observed_at),
        }.items()
        if value is not None
    }
    return InfoPlaceCard(
        question_type=QuestionType.REALTIME_COMMERCIAL,
        answer_fields=fields,
        place_name=place_name,
        population_current_level=result.population_current_level,
        population_observed_at=format_citydata_timestamp(result.population_observed_at),
        population_forecasts=[
            PopulationForecastBar(
                forecast_at=forecast.forecast_at,
                congestion_level=forecast.congestion_level,
                population_min=forecast.population_min,
                population_max=forecast.population_max,
            )
            for forecast in result.population_forecasts
        ],
        realtime_area_name=result.area_name,
        realtime_observed_at=format_citydata_timestamp(result.observed_at),
        realtime_source_url=result.source_url,
        realtime_detail_items=_to_realtime_detail_items(result.detail_items),
        seoul_realtime_summary=_to_seoul_realtime_summary(
            result.realtime_summary,
            observed_at=result.population_observed_at,
            forecasts=result.population_forecasts,
            current_level=result.population_current_level,
        ),
    )


def _to_realtime_population_card(
    result: RealtimePopulationInfoResult,
) -> InfoPlaceCard | None:
    """현재 인구 혼잡도와 12시간 예측을 concentration 카드에 함께 싣는다."""

    place_name = result.resolved_place_name or result.requested_place_name
    if place_name is None:
        return None

    fields = {
        key: value
        for key, value in {
            "실시간 기준 지역": result.area_name,
            "현재 인구 혼잡도": result.current_congestion_level,
            "기준 시각": format_citydata_timestamp(result.observed_at),
            "안내": result.current_congestion_message,
        }.items()
        if value is not None
    }
    return InfoPlaceCard(
        question_type=QuestionType.CONCENTRATION,
        answer_fields=fields,
        place_name=place_name,
        population_current_level=result.current_congestion_level,
        population_current_message=result.current_congestion_message,
        population_observed_at=format_citydata_timestamp(result.observed_at),
        population_peak_forecast_summary=_summarize_population_peak(
            result.observed_at, result.population_forecasts
        ),
        population_forecasts=[
            PopulationForecastBar(
                forecast_at=forecast.forecast_at,
                congestion_level=forecast.congestion_level,
                population_min=forecast.population_min,
                population_max=forecast.population_max,
            )
            for forecast in result.population_forecasts
        ],
        realtime_area_name=result.area_name,
        realtime_observed_at=format_citydata_timestamp(result.observed_at),
        realtime_source_url=result.source_url,
        realtime_map_url=result.map_url,
        realtime_detail_items=(
            [
                RealtimeInfoDetailItem(
                    title="혼잡도 안내",
                    subtitle=result.current_congestion_level,
                    details={"안내": result.current_congestion_message},
                )
            ]
            if result.current_congestion_message is not None
            else []
        ),
        seoul_realtime_summary=_to_seoul_realtime_summary(
            result.realtime_summary,
            observed_at=result.observed_at,
            forecasts=result.population_forecasts,
            current_level=result.current_congestion_level,
        ),
    )


def _to_realtime_detail_items(
    items: list[ContextRealtimeInfoDetailItem],
) -> list[RealtimeInfoDetailItem]:
    """C의 실시간 도시데이터 상세 항목을 최종 응답 스키마로 옮긴다."""

    return [
        RealtimeInfoDetailItem(
            title=item.title,
            subtitle=item.subtitle,
            details=item.details,
            thumbnail_url=item.thumbnail_url,
            external_url=item.external_url,
            latitude=item.latitude,
            longitude=item.longitude,
        )
        for item in items
    ]
