import pytest

from app import tracing
from app.investigator import investigate


@pytest.fixture
def exporter():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    ex = InMemorySpanExporter()
    assert tracing.setup_tracing(ex)
    yield ex
    tracing.reset()


def test_noop_when_unconfigured():
    tracing.reset()
    with tracing.span("x", a=1) as s:
        s.set("k", "v")  # must not raise


def test_investigation_emits_spans_without_leaking_content(exporter):
    seq = iter([
        {"content": "", "tool_calls": [{"id": "1", "name": "ticket_history",
                                        "arguments": {"cell_id": "CELL_001"}}]},
        {"content": "SECRET-NOTES done", "tool_calls": []}])
    investigate({"cell_id": "CELL_001", "kpi": "prb_utilization_pct"},
                chat_fn=lambda m, t: next(seq), run_fn=lambda n, a: [])
    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert "tool.ticket_history" in names and names.count("agent.model_turn") == 2
    assert "agent.summary" in names
    dumped = repr([(s.name, dict(s.attributes)) for s in spans])
    assert "SECRET-NOTES" not in dumped and "CELL_001" not in dumped


def test_exception_is_recorded_and_propagates(exporter):
    with pytest.raises(ValueError), tracing.span("boom"):
        raise ValueError("x")
    sp = exporter.get_finished_spans()[0]
    assert sp.attributes["error.type"] == "ValueError"
