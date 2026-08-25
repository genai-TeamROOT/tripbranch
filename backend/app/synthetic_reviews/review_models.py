"""합성 리뷰 Gemini 구조화 출력 계약."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.synthetic_reviews.review_plans import DEFAULT_REVIEWS_PER_PLACE
from app.synthetic_reviews.sentiments import Sentiment


class ClaimGrounding(StrEnum):
    TOUR_API = "TOUR_API"
    SYNTHETIC_SCENARIO = "SYNTHETIC_SCENARIO"


class SyntheticReviewClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    text: str = Field(min_length=1, max_length=300)
    grounding: ClaimGrounding
    source_field: str | None = Field(default=None, alias="sourceField")
    source_value: str | None = Field(default=None, alias="sourceValue")

    @model_validator(mode="after")
    def validate_grounding_fields(self) -> SyntheticReviewClaim:
        if self.grounding is ClaimGrounding.TOUR_API:
            if not self.source_field or not self.source_value:
                raise ValueError("TOUR_API claim에는 sourceField/sourceValue가 필요합니다.")
        elif self.source_field is not None or self.source_value is not None:
            raise ValueError(
                "SYNTHETIC_SCENARIO claim에는 sourceField/sourceValue를 쓸 수 없습니다."
            )
        return self


class SyntheticReview(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    review_index: int = Field(
        alias="reviewIndex", ge=0, le=DEFAULT_REVIEWS_PER_PLACE - 1
    )
    persona_type: str = Field(alias="personaType", min_length=1, max_length=200)
    sentiment: Sentiment
    visit_context: str = Field(alias="visitContext", min_length=1, max_length=300)
    review_text: str = Field(alias="reviewText", min_length=1, max_length=1200)
    claims: list[SyntheticReviewClaim] = Field(min_length=1, max_length=12)


class SyntheticReviewBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviews: list[SyntheticReview] = Field(
        min_length=DEFAULT_REVIEWS_PER_PLACE,
        max_length=DEFAULT_REVIEWS_PER_PLACE,
    )


__all__ = [
    "ClaimGrounding",
    "SyntheticReview",
    "SyntheticReviewBatch",
    "SyntheticReviewClaim",
]
