"""신원 검증 테스트용 키·토큰 도구.

실제 Supabase를 부르지 않는다. 테스트 전용 EC 키쌍을 만들어 우리가 직접 서명하고,
그 공개키를 JWKS로 돌려주도록 조회 함수를 바꿔 끼운다.
"""

from __future__ import annotations

import json
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import jwks
from app.config import settings

TEST_KID = "test-kid-1"
TEST_SUPABASE_URL = "https://test.supabase.co"
TEST_ISSUER = f"{TEST_SUPABASE_URL}/auth/v1"


@pytest.fixture
def signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def public_jwk(key: ec.EllipticCurvePrivateKey, kid: str = TEST_KID) -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "ES256"})
    return jwk


def make_token(
    key: ec.EllipticCurvePrivateKey,
    *,
    kid: str | None = TEST_KID,
    algorithm: str = "ES256",
    **claim_overrides: Any,
) -> str:
    claims: dict[str, Any] = {
        "sub": "3f1a9c04-0000-4000-8000-000000000001",
        "iss": TEST_ISSUER,
        "aud": "authenticated",
        "exp": 4102444800,  # 2100년
        "is_anonymous": True,
    }
    claims.update(claim_overrides)
    headers = {"kid": kid} if kid else {}
    return jwt.encode(claims, key, algorithm=algorithm, headers=headers)


@pytest.fixture(autouse=True)
def configured_auth(
    monkeypatch: pytest.MonkeyPatch,
    signing_key: ec.EllipticCurvePrivateKey,
) -> None:
    """SUPABASE_URL을 테스트 값으로 두고, JWKS 조회를 테스트 공개키로 바꿔 끼운다."""
    monkeypatch.setattr(settings, "supabase_url", TEST_SUPABASE_URL)
    jwks.reset_cache()

    async def fake_fetch() -> dict[str, Any]:
        return {"keys": [public_jwk(signing_key)]}

    monkeypatch.setattr(jwks, "_fetch_jwks", fake_fetch)
    yield
    jwks.reset_cache()
