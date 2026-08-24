"""Trace 기록 시나리오.

계약 문서: docs/package-b/llmops-trace-contract-v1.md
"""

import pytest

from app.state import service as svc
from app.state import trace as trace_module
from app.state.store import InMemoryStateStore


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


def record_trace(store, **kwargs) -> svc.RecordTraceResponse:
    """실행 단계 기록 호출. 테스트 편의용 헬퍼."""
    kwargs.setdefault("session_id", "sess_test")
    kwargs.setdefault("run_id", "run_test")
    kwargs.setdefault("step", "llm_interpret")
    return svc.record_trace(svc.RecordTraceRequest(**kwargs), store=store)


class TestRecordTrace:
    def test_trace_id를_발급하고_반환한다(self, store):
        response = record_trace(store)

        assert response.trace_id.startswith("trace_")

    def test_호출마다_다른_trace_id가_발급된다(self, store):
        first = record_trace(store)
        second = record_trace(store)

        assert first.trace_id != second.trace_id

    def test_전달한_값이_그대로_저장된다(self, store):
        record_trace(
            store,
            step="scoring",
            prompt_version="intent_v1.2",
            scoring_version="score_v0.3",
            variant_id="variant_b",
            latency_ms=120,
            token_usage=350,
            error_type=None,
        )

        [saved] = trace_module.get_traces(store, "sess_test")
        assert saved.step == "scoring"
        assert saved.prompt_version == "intent_v1.2"
        assert saved.scoring_version == "score_v0.3"
        assert saved.variant_id == "variant_b"
        assert saved.latency_ms == 120
        assert saved.token_usage == 350
        assert saved.error_type is None

    def test_임의의_step_문자열도_거부하지_않는다(self, store):
        """B는 step 이름의 의미를 판단하지 않는다. (경계 원칙)"""
        record_trace(store, step="anything_the_caller_wants")

        [saved] = trace_module.get_traces(store, "sess_test")
        assert saved.step == "anything_the_caller_wants"

    def test_선택_필드를_생략하면_None으로_남는다(self, store):
        record_trace(store, step="tool_fetch")

        [saved] = trace_module.get_traces(store, "sess_test")
        assert saved.prompt_version is None
        assert saved.scoring_version is None
        assert saved.variant_id is None
        assert saved.latency_ms is None
        assert saved.token_usage is None
        assert saved.error_type is None

    def test_오류_기록도_받는다(self, store):
        record_trace(store, step="llm_interpret", error_type="timeout")

        [saved] = trace_module.get_traces(store, "sess_test")
        assert saved.error_type == "timeout"


class TestAppendOnly:
    def test_같은_세션에서_여러_건이_순서대로_쌓인다(self, store):
        record_trace(store, run_id="run_1", step="llm_interpret")
        record_trace(store, run_id="run_1", step="tool_fetch")
        record_trace(store, run_id="run_2", step="scoring")

        saved = trace_module.get_traces(store, "sess_test")
        assert [t.step for t in saved] == ["llm_interpret", "tool_fetch", "scoring"]

    def test_기존_기록을_지우는_메서드가_없다(self, store):
        assert not hasattr(store, "delete_trace")


class TestSessionIsolation:
    def test_다른_세션의_기록은_섞이지_않는다(self, store):
        record_trace(store, session_id="sess_a", step="llm_interpret")
        record_trace(store, session_id="sess_b", step="scoring")

        assert [t.step for t in trace_module.get_traces(store, "sess_a")] == [
            "llm_interpret"
        ]
        assert [t.step for t in trace_module.get_traces(store, "sess_b")] == [
            "scoring"
        ]

    def test_기록이_없는_세션은_빈_목록을_반환한다(self, store):
        assert trace_module.get_traces(store, "sess_never_used") == []
