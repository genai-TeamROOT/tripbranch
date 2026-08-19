"""프롬프트 라이브러리 메타데이터의 진입점.

각 인텐트 폴더의 ``meta.yaml``이 슬롯·소유자·현재 관리 버전의 기준이다. YAML을
런타임 설정값으로 해석하는 기능과 조합 해시 기반 Trace 값은 후속 작업에서 이 모듈에
추가한다. 현재 실행 경로는 Markdown 템플릿만 로드하므로 새 의존성을 만들지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from app.prompts.loader import PROMPT_ROOT


def metadata_paths() -> list[Path]:
    """라이브러리 안의 인텐트별 메타데이터 파일 목록을 반환한다."""

    return sorted(PROMPT_ROOT.glob("*/meta.yaml"))
