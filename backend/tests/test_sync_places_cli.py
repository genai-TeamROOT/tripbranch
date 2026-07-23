from __future__ import annotations

import pytest

from app.config import Settings
from scripts.sync_places import build_parser, run


def test_sync_places_parser_accepts_safety_options() -> None:
    args = build_parser().parse_args(
        [
            "--area-code",
            "11",
            "--district-code",
            "110",
            "--dry-run",
            "--details-limit",
            "3",
            "--force-details",
        ]
    )

    assert args.area_code == "11"
    assert args.district_code == "110"
    assert args.dry_run is True
    assert args.details_limit == 3
    assert args.force_details is True


@pytest.mark.asyncio
async def test_sync_places_requires_server_secrets_before_network() -> None:
    settings = Settings(
        _env_file=None,
        tour_api_service_key="",
        supabase_url="https://project.supabase.co",
        supabase_secret_key="",
    )
    args = build_parser().parse_args(["--dry-run"])

    with pytest.raises(ValueError, match="TOUR_API_SERVICE_KEY"):
        await run(args, settings)
