"""집중률 장소 매핑 CSV 적재 입력 검증 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.import_concentration_mappings import load_mapping_payloads

_MAPPING_CSV = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "data"
    / "concentration_place_mapping.csv"
)


def test_current_mapping_csv_builds_unique_matched_payloads() -> None:
    payloads, csv_row_count, unmatched_count = load_mapping_payloads(_MAPPING_CSV)

    assert csv_row_count == 112
    assert len(payloads) == 100
    assert unmatched_count == 12
    assert len({str(payload["content_id"]) for payload in payloads}) == 100

    blue_house = next(
        payload for payload in payloads if payload["content_id"] == "126533"
    )
    assert blue_house["primary_concentration_name"] == "청와대 앞길"
    assert blue_house["concentration_aliases"] == ["청와대"]
    assert blue_house["match_method"] == "exact_with_alias"


def test_duplicate_matched_content_id_is_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "duplicate.csv"
    csv_path.write_text(
        "content_id,place_title,concentration_title,concentration_aliases,"
        "match_status,match_method,confidence_score,verified_at\n"
        '1,장소,집중률 장소,[],matched,exact,1.0000,\n'
        '1,장소,별칭 장소,[],matched,manual,0.8000,\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="content_id가 중복"):
        load_mapping_payloads(csv_path)


def test_blank_alias_is_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "blank-alias.csv"
    csv_path.write_text(
        "content_id,place_title,concentration_title,concentration_aliases,"
        "match_status,match_method,confidence_score,verified_at\n"
        '1,장소,집중률 장소,"["" ""]",matched,exact_with_alias,1.0000,\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="빈 concentration alias"):
        load_mapping_payloads(csv_path)
