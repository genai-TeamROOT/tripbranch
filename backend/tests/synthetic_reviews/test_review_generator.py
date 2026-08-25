from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.synthetic_reviews import (
    ClaimGrounding,
    GeminiSyntheticReviewGenerator,
    PlacePersonaInput,
    SyntheticReviewBatch,
    assess_sentiment,
    build_official_facts,
    generate_personas,
    generate_review_plans,
    validate_review_batch,
)


def _row() -> dict[str, object]:
    return {
        "content_id": "126508",
        "content_type_id": "14",
        "title": "테스트 문화시설",
        "address": "서울특별시 종로구",
        "lcls_systm1": "VE",
        "lcls_systm2": "VE07",
        "lcls_systm3": "VE070100",
        "operating_hours_raw": "09:00~18:00",
        "rest_date_raw": "매주 화요일",
        "parking_info_raw": "불가능",
        "parking_fee_raw": "무료",
        "use_fee_raw": "3,000원",
        "discount_info_raw": None,
        "info_center_raw": "02-000-0000",
        "baby_carriage_raw": "없음",
        "pet_raw": "불가",
        "credit_card_raw": "가능",
        "restroom_raw": "있음",
        "google_reviews": "사용하면 안 되는 구글 리뷰",
        "naver_blog_text": "사용하면 안 되는 네이버 글",
    }


def _inputs():
    row = _row()
    facts = build_official_facts(row)
    place = PlacePersonaInput(
        **{
            field: facts.get(field)
            for field in PlacePersonaInput.__dataclass_fields__
        }
    )
    personas = generate_personas(place)
    plans = generate_review_plans(personas)
    sentiments = tuple(assess_sentiment(place, plan) for plan in plans)
    return facts, plans, sentiments


def _valid_payload() -> dict[str, object]:
    facts, plans, sentiments = _inputs()

    def claims_for(plan):
        if not plan.evidence_fields:
            return [
                {
                    "text": "여행자의 방문 목적과 일정에 맞는지 고민하고 있다.",
                    "grounding": ClaimGrounding.SYNTHETIC_SCENARIO.value,
                }
            ]
        source_field = plan.evidence_fields[0]
        return [
            {
                "text": "공식 장소 정보에 기록된 조건이다.",
                "grounding": ClaimGrounding.TOUR_API.value,
                "sourceField": source_field,
                "sourceValue": facts[source_field],
            }
        ]

    return {
        "reviews": [
            {
                "reviewIndex": plan.review_index,
                "personaType": plan.persona_id,
                "sentiment": sentiments[index].sentiment.value,
                "visitContext": plan.visit_context,
                "reviewText": (
                    "공식 정보를 먼저 확인했다. 방문 목적과 맞는지 살펴보았다. "
                    "다른 일정과의 순서도 생각해 보았다. 확인한 내용을 바탕으로 선택하려 한다."
                ),
                "claims": claims_for(plan),
            }
            for index, plan in enumerate(plans)
        ]
    }


def _valid_wire_payload() -> dict[str, object]:
    payload = _valid_payload()
    return {
        "reviews": [
            {
                "reviewIndex": review["reviewIndex"],
                "reviewSentences": [
                    "공식 정보를 먼저 확인했다",
                    "방문 목적과 맞는지 살펴보았다",
                    "다른 일정과의 순서도 생각해 보았다",
                    "확인한 내용을 바탕으로 선택하려 한다",
                ],
                "claims": review["claims"],
            }
            for review in payload["reviews"]  # type: ignore[union-attr]
        ]
    }


class _Models:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    async def generate_content(self, **kwargs: object):
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed=None,
            text=json.dumps(self.payload, ensure_ascii=False),
        )


def _generator(payload: dict[str, object]):
    models = _Models(payload)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    generator = GeminiSyntheticReviewGenerator(
        api_key="", model_name="test-model", client=client
    )
    return generator, models


def test_공식_입력은_허용된_tour_api_필드만_남긴다() -> None:
    facts = build_official_facts(_row())

    assert facts["title"] == "테스트 문화시설"
    assert "google_reviews" not in facts
    assert "naver_blog_text" not in facts


@pytest.mark.asyncio
async def test_장소당_한_번의_llm_호출로_리뷰_5개를_생성한다() -> None:
    facts, plans, sentiments = _inputs()
    generator, models = _generator(_valid_wire_payload())

    batch = await generator.generate(
        facts=facts, plans=plans, sentiments=sentiments
    )

    assert len(batch.reviews) == 5
    assert all(review.review_text.count(".") == 4 for review in batch.reviews)
    assert all(
        review.persona_type == plans[review.review_index].persona_id
        for review in batch.reviews
    )
    assert len(models.calls) == 1
    config = models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None
    assert config.response_json_schema is None
    assert "내부 필드명" in config.system_instruction
    assert "상투적인 문구" in config.system_instruction
    assert "한국어 완결 문장을 정확히" in config.system_instruction
    review_schema = config.response_schema.model_fields["reviews"].annotation
    assert "personaType" not in str(review_schema)
    assert "sentiment" not in str(review_schema)
    assert "visitContext" not in str(review_schema)
    assert "google" not in str(models.calls[0]["contents"]).casefold()
    assert "naver" not in str(models.calls[0]["contents"]).casefold()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("personaType", "OTHER_PERSONA", "personaType"),
        ("visitContext", "다른 방문 상황", "visitContext"),
        ("sentiment", "POSITIVE", "sentiment"),
    ],
)
def test_계획과_다른_출력은_거부한다(field: str, value: str, message: str) -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][0][field] = value  # type: ignore[index]
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match=message):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


def test_계획에_없는_공식_출처는_거부한다() -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    claim = payload["reviews"][0]["claims"][0]  # type: ignore[index]
    claim["sourceField"] = "parking_info_raw"
    claim["sourceValue"] = facts["parking_info_raw"]
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="허용되지 않은 출처"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


def test_공식_출처값을_바꾸면_거부한다() -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][0]["claims"][0]["sourceValue"] = "12"  # type: ignore[index]
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="출처 값 불일치"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


def test_공식_정보에_없는_수치는_거부한다() -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][0]["reviewText"] = (  # type: ignore[index]
        "공식 정보를 확인했다. 방문 목적을 정했다. 다른 일정도 살펴보았다. "
        "걸어서 27분 정도 걸리는 장소로 보인다."
    )
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="없는 수치"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


@pytest.mark.parametrize(
    "review_text",
    [
        "첫 문장이다. 두 번째 문장이다. 세 번째 문장이다.",
        (
            "첫 문장이다. 두 번째 문장이다. 세 번째 문장이다. "
            "네 번째 문장이다. 다섯 번째 문장이다. 여섯 번째 문장이다."
        ),
    ],
)
def test_리뷰가_4개에서_5개_문장이_아니면_거부한다(review_text: str) -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][0]["reviewText"] = review_text  # type: ignore[index]
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="4~5문장"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


def test_합성_시나리오_claim의_수치와_객관적_사실을_거부한다() -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][0]["claims"] = [  # type: ignore[index]
        {
            "text": "대기 시간이 20분으로 길다.",
            "grounding": "SYNTHETIC_SCENARIO",
        }
    ]
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="구체적인 수치"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


def test_공식_부정_정보를_긍정으로_뒤집은_claim은_거부한다() -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][1]["claims"] = [  # type: ignore[index]
        {
            "text": "주차가 가능하다.",
            "grounding": "TOUR_API",
            "sourceField": "parking_info_raw",
            "sourceValue": "불가능",
        }
    ]
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="모순"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


def test_실제_방문을_가장하는_표현은_거부한다() -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][0]["reviewText"] = (  # type: ignore[index]
        "공식 정보를 확인했다. 방문 목적을 정했다. 다른 일정도 살펴보았다. "
        "지난주 직접 방문해 보니 좋았다."
    )
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="가장"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


@pytest.mark.parametrize(
    "review_text",
    [
        "content_type_id 14인 장소라 방문을 고려하고 있다.",
        "콘텐츠 타입 14에 해당하는 곳이다.",
        "관광지 타입 14라서 일정에 넣어 보려 한다.",
        "operating_hours_raw를 확인해 방문 시간을 정하려 한다.",
    ],
)
def test_리뷰_본문에_내부_필드명이나_코드를_노출하면_거부한다(
    review_text: str,
) -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][0]["reviewText"] = (  # type: ignore[index]
        f"공식 정보를 확인했다. 방문 목적을 정했다. 다른 일정도 살펴보았다. {review_text}"
    )
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="내부 필드명"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


@pytest.mark.parametrize(
    "review_text",
    [
        "주차 공간이 넉넉해서 이동하기에 편리하겠다.",
        "전통적인 볼거리가 있어 온 가족에게 알맞은 곳이다.",
        "문의처가 있어 일정 변경에도 유연하게 대처할 수 있다.",
        "고령의 가족과도 무리 없이 소화할 수 있는 일정이다.",
        "관광지 분류라 다른 명소와 연계하기에도 무난하다.",
        "차분한 분위기 속에서 둘러보기 좋은 장소다.",
    ],
)
def test_공식_사실을_근거_없는_편의성과_적합성으로_확대하면_거부한다(
    review_text: str,
) -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][0]["reviewText"] = (  # type: ignore[index]
        f"공식 정보를 확인했다. 방문 목적을 정했다. 다른 일정도 살펴보았다. {review_text}"
    )
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="근거 없는 평가"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


@pytest.mark.parametrize(
    "review_text",
    [
        "아이들이 좋아할 만한 교육적인 장소다.",
        "고령자도 걷기 편하고 휴식 공간이 많아 보인다.",
        "연인과 가기 좋은 로맨틱한 데이트 명소다.",
    ],
)
def test_동행자_유형만으로_장소_적합성을_추론하면_거부한다(
    review_text: str,
) -> None:
    facts, plans, sentiments = _inputs()
    payload = _valid_payload()
    payload["reviews"][1]["reviewText"] = (  # type: ignore[index]
        f"공식 정보를 확인했다. 방문 목적을 정했다. 다른 일정도 살펴보았다. {review_text}"
    )
    batch = SyntheticReviewBatch.model_validate(payload)

    with pytest.raises(ValueError, match="동행자 유형"):
        validate_review_batch(
            batch, facts=facts, plans=plans, sentiments=sentiments
        )


def test_json_schema가_리뷰_5개를_강제한다() -> None:
    payload = _valid_payload()
    payload["reviews"] = payload["reviews"][:4]  # type: ignore[index]

    with pytest.raises(ValueError):
        SyntheticReviewBatch.model_validate(payload)
