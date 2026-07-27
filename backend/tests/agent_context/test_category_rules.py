"""A 장소 조건을 C의 TourAPI 분류 조회 계획으로 바꾸는 룰을 검증한다."""

from app.agent_context.category_rules import build_category_query_plan


def test_empty_categories_plan_unfiltered_search() -> None:
    plan = build_category_query_plan([], [])

    assert plan.filters == (None,)
    assert plan.resolved_place_types == ()
    assert plan.resolved_place_tags == ()


def test_place_type_maps_to_content_type_filter() -> None:
    plan = build_category_query_plan(["restaurant"], [])

    assert [item.content_type_id for item in plan.filters if item] == ["39"]
    assert plan.resolved_place_types == ("restaurant",)


def test_multiple_place_types_preserve_request_order() -> None:
    plan = build_category_query_plan(
        ["cultural_facility", "restaurant"],
        [],
    )

    assert [item.content_type_id for item in plan.filters if item] == ["14", "39"]


def test_place_tag_uses_small_category_and_infers_place_type() -> None:
    plan = build_category_query_plan([], ["카페"])

    assert len(plan.filters) == 1
    category_filter = plan.filters[0]
    assert category_filter is not None
    assert category_filter.content_type_id == "39"
    assert category_filter.lcls_systm1 == "FD"
    assert category_filter.lcls_systm2 == "FD05"
    assert category_filter.lcls_systm3 == "FD050100"
    assert plan.resolved_place_types == ("restaurant",)
    assert plan.resolved_place_tags == ("카페",)


def test_broad_tag_expands_to_multiple_small_category_filters() -> None:
    plan = build_category_query_plan(["attraction"], ["공원"])

    assert [item.lcls_systm3 for item in plan.filters if item] == [
        "VE030100",
        "VE030200",
        "VE030300",
        "VE030400",
        "VE030500",
    ]


def test_duplicate_conditions_are_removed_without_changing_order() -> None:
    plan = build_category_query_plan(
        [" RESTAURANT ", "restaurant"],
        ["카페", " 카페 "],
    )

    assert plan.resolved_place_types == ("restaurant",)
    assert plan.resolved_place_tags == ("카페",)
    assert len(plan.filters) == 1


def test_unknown_conditions_are_reported_without_broadening_search() -> None:
    plan = build_category_query_plan(["unknown"], ["없는태그"])

    assert plan.filters == ()
    assert plan.unsupported_place_types == ("unknown",)
    assert plan.unsupported_place_tags == ("없는태그",)
    assert plan.has_unsupported_conditions is True


def test_tag_conflicting_with_explicit_type_is_reported() -> None:
    plan = build_category_query_plan(["attraction"], ["카페"])

    assert plan.filters == ()
    assert plan.resolved_place_types == ("attraction",)
    assert plan.resolved_place_tags == ()
    assert plan.conflicting_place_tags == ("카페",)
    assert plan.has_conflicts is True


def test_tag_filters_take_priority_over_broad_type_filter() -> None:
    plan = build_category_query_plan(
        ["restaurant", "cultural_facility"],
        ["카페", "박물관"],
    )

    assert [item.lcls_systm3 for item in plan.filters if item] == [
        "FD050100",
        "VE070100",
    ]
