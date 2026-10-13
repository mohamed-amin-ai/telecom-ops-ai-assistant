from app import agent


def _state():
    return {"alert": {"cell": "CELL_001"}, "profile": {"anomalous": True},
            "runbook": [{"source": "01_high_prb_utilization.md", "chunk": 1, "text": "Check load."}]}


def test_fix_severity_replaces_literal_placeholder():
    out = agent.fix_severity("Done.\nSeverity: P3 (reason)")
    assert "undetermined" in out and "P3" not in out


def test_fix_severity_keeps_real_reason():
    t = "Severity: P2 (busy-hour congestion, per the severity rules)"
    assert agent.fix_severity(t) == t


def test_retries_once_when_no_citation(monkeypatch):
    calls = []

    def fake_chat(msgs):
        calls.append(msgs)
        return ("Check load [01_high_prb_utilization.md#1]. Severity: P2 (busy hour)"
                if len(calls) > 1 else "Check load. Severity: P3 (reason)")

    monkeypatch.setattr(agent, "chat", fake_chat)
    out = agent.diagnose_node(_state())["diagnosis"]
    assert len(calls) == 2
    assert "[01_high_prb_utilization.md#1]" in out and "unverified" not in out


def test_no_retry_when_cited(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "chat", lambda m: calls.append(m) or "x [01_high_prb_utilization.md#1]")
    agent.diagnose_node(_state())
    assert len(calls) == 1


def test_severity_of_reads_last_severity_line():
    from app.tools import _severity_of
    assert _severity_of("x\nSeverity: P3 (single cell)") == "P3"
    assert _severity_of("Severity: undetermined (need data)") == "undetermined"
    assert _severity_of("no severity here") is None


def test_threshold_check_not_reached():
    out = agent.threshold_check({"description": "PRB above 85%"}, {"recent_max": 76.77})
    assert "did NOT reach" in out and "85" in out


def test_threshold_check_reached_and_absent():
    assert "reached the alert" in agent.threshold_check({"description": "PRB above 85%"}, {"recent_max": 90})
    assert agent.threshold_check({"description": "slow"}, {"recent_max": 90}) == ""
    assert agent.threshold_check({"description": "above 85%"}, None) == ""
