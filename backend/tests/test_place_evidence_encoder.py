"""ko-sroberta 인코더의 지연 로딩과 설치 안내 테스트 (torch 없이 돈다)."""

from __future__ import annotations

import builtins
import sys
import types
from typing import Any

import pytest

from app.providers.place_evidence_encoder import MODEL_NAME, KoSrobertaEncoder


class _Vector:
    def tolist(self) -> list[float]:
        return [0.1] * 768


class _FakeModel:
    def __init__(self, name: str) -> None:
        self.name = name

    def encode(self, text: str, normalize_embeddings: bool = False) -> _Vector:
        assert normalize_embeddings is True, (
            "적재를 정규화 임베딩으로 했으므로 질의도 같은 조건이어야 유사도가 의미를 갖는다"
        )
        return _Vector()


@pytest.fixture
def loaded_names(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """sentence_transformers를 가짜 모듈로 바꿔 생성자 호출을 센다."""
    names: list[str] = []

    def ctor(name: str) -> _FakeModel:
        names.append(name)
        return _FakeModel(name)

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = ctor  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return names


def test_model_is_loaded_once_and_reused(loaded_names: list[str]) -> None:
    """요청마다 1.2GB 모델을 다시 올리면 서버가 버티지 못한다."""
    encoder = KoSrobertaEncoder()

    encoder.encode("조용한 곳")
    encoder.encode("혼자 쉬기 좋은 곳")

    assert loaded_names == [MODEL_NAME]


def test_model_is_not_loaded_until_used(loaded_names: list[str]) -> None:
    """생성만으로 모델을 올리면 취향 검색을 안 쓰는 배포에서도 1.2GB를 문다."""
    KoSrobertaEncoder()

    assert loaded_names == []


def test_warmup_loads_the_model_up_front(loaded_names: list[str]) -> None:
    """lifespan에서 미리 올려두지 않으면 첫 요청이 적재 시간을 뒤집어쓴다."""
    KoSrobertaEncoder().warmup()

    assert loaded_names == [MODEL_NAME]


def test_encode_returns_768_floats(loaded_names: list[str]) -> None:
    """RPC가 vector(768)을 요구한다 — 차원이 다르면 Postgres가 거부한다."""
    assert len(KoSrobertaEncoder().encode("조용한 곳")) == 768


def test_missing_dependency_explains_how_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """선택 의존성이라 미설치 환경에서 ImportError만 보면 원인을 알기 어렵다."""
    real_import = builtins.__import__

    def blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    monkeypatch.setattr(builtins, "__import__", blocked)

    with pytest.raises(RuntimeError, match="embeddings"):
        KoSrobertaEncoder().encode("조용한 곳")
