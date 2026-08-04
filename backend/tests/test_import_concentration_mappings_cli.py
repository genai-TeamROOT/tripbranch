"""집중률 장소 매핑 CSV 적재 입력 검증 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.import_concentration_mappings import (
    latest_mapping_csv,
    load_mapping_payloads,
)

# 매핑 CSV는 생성일이 파일명에 붙어 재생성마다 바뀐다. 최신본을 그대로 검증한다.
_MAPPING_CSV = latest_mapping_csv()


def test_current_mapping_csv_builds_unique_matched_payloads() -> None:
    """저장소에 있는 최신 매핑 CSV가 그대로 적재 가능한 형태인지 확인한다."""
    assert _MAPPING_CSV is not None, "supabase/data에 매핑 CSV가 없습니다."
    payloads, csv_row_count, unmatched_count = load_mapping_payloads(_MAPPING_CSV)

    assert payloads
    assert csv_row_count == len(payloads) + unmatched_count
    # content_id가 PK라 중복이 있으면 적재가 실패한다.
    assert len({str(payload["content_id"]) for payload in payloads}) == len(payloads)
    # 검색어는 공백이 있으면 조회가 0건이 된다(D-043).
    assert all(
        not any(character.isspace() for character in str(payload["concentration_search_key"]))
        for payload in payloads
        if payload["concentration_search_key"]
    )

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
