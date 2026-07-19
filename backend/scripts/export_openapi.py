# FastAPI 앱을 실행하지 않고 OpenAPI 스키마(JSON)만 backend/openapi.json으로 추출하는 스크립트.
# 사용법: `npm run export-openapi`(backend/package.json) 또는 이 파일을 직접 python으로 실행.
# 프론트의 `npm run generate:api-types`가 이 산출물을 입력으로 TS 타입을 생성한다.

"""Writes the FastAPI app's OpenAPI schema to backend/openapi.json without
starting a server. Used by `npm run generate:api-types` (see README)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402

OUTPUT_PATH = BACKEND_ROOT / "openapi.json"


def main() -> None:
    schema = app.openapi()
    OUTPUT_PATH.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
