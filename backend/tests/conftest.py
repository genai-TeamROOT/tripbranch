# pytest 공용 픽스처. TestClient(app)를 제공해 API 레벨 테스트에서 재사용한다.
# 기본 Settings(모든 Provider=fake)로 앱이 뜨므로 별도 mocking 없이 실제 HTTP 흐름을 검증할 수 있다.

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
