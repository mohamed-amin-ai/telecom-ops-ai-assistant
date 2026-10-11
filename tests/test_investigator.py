import dataclasses
from unittest.mock import MagicMock

import pytest

from app import investigator as inv

ALERT = {"cell_id": "CELL_001", "kpi": "prb_utilization_pct", "description": "high PRB"}


def call(name, args, i=0):
    return {"id": f"c{i}", "name": name, "arguments": args}


def scripted(*turns):
    """chat_fn that returns the given turns in order; records what it was sent."""
    it = iter(turns)
    sent = []

    def fn(messages, tools):
        sent.append((list(messages), tools))
        return next(it)
    fn.sent = sent
    return fn


def turn(*calls, text=""):
    return {"content": text, "tool_calls": list(calls)}


def runner(log):
    def run(name, args):
        log.append((name, args))
        return {"kpi_profile": {"z": 3.1}, "get_kpis": [{"ts": "t", "value": 1}],
                "ticket_history": [], "search_runbooks": [
                    {"source": "a.md", "chunk": 0, "text": "x"}]}[name]
    return run


def test_create_ticket_is_not_a_tool_and_is_rejected_if_named():
    assert "create_ticket" not in inv.TOOL_NAMES
    assert all(t["function"]["name"] != "create_ticket" for t in inv.TOOL_SPECS)
    log = []
    chat = scripted(turn(call("create_ticket", {"cell_id": "CELL_001"})), turn(text="done"))
    r = inv.investigate(ALERT, chat, runner(log))
    assert log == []  # never executed
    assert r["trace"][0]["outcome"] == "rejected"
    assert "unknown tool" in chat.sent[1][0][-1]["content"]


def test_step_limit_stops_the_loop_and_forces_a_no_tools_summary():
    log = []
    forever = [turn(call("search_runbooks", {"query": f"q{i}"}, i))
               for i in range(20)]
    chat = scripted(*forever[:3], turn(text="summary of findings"))
    r = inv.investigate(ALERT, chat, runner(log), max_steps=3)
    assert r["stopped"] == "step_limit" and len(log) == 3
    assert r["notes"] == "summary of findings"
    assert chat.sent[-1][1] == []  # final turn offers no tools


def test_calls_beyond_budget_inside_one_turn_are_not_executed():
    log = []
    many = turn(*[call("search_runbooks", {"query": f"q{i}"}, i)
                  for i in range(6)])
    chat = scripted(many, turn(text="ok"))
    r = inv.investigate(ALERT, chat, runner(log), max_steps=2)
    assert len(log) == 2
    assert [t["outcome"] for t in r["trace"]].count("budget") == 4


def test_stops_by_itself_and_collects_evidence():
    log = []
    chat = scripted(
        turn(call("kpi_profile", {"cell_id": "CELL_001", "kpi": "prb_utilization_pct"}, 1),
             call("search_runbooks", {"query": "high prb"}, 2)),
        turn(call("search_runbooks", {"query": "high prb"}, 3)),  # duplicate
        turn(text="PRB is high; runbook 01 applies"))
    r = inv.investigate(ALERT, chat, runner(log))
    assert r["stopped"] == "done" and r["profile"] == {"z": 3.1}
    assert len(r["runbook"]) == 1  # merged and de-duplicated
    assert [t["outcome"] for t in r["trace"]] == ["ok", "ok", "duplicate"]
    assert len(log) == 2  # the duplicate did not hit the tool again


def test_no_tool_call_is_reported():
    r = inv.investigate(ALERT, scripted(turn(text="I think it is fine")), runner([]))
    assert r["stopped"] == "no_tools" and r["trace"] == []


def test_tool_error_is_shown_to_the_model_not_raised():
    def boom(name, args):
        raise RuntimeError("db down")
    chat = scripted(turn(call("kpi_profile", {"cell_id": "CELL_001", "kpi": "prb_utilization_pct"})),
                    turn(text="could not read KPIs"))
    r = inv.investigate(ALERT, chat, boom)
    assert r["trace"][0]["outcome"] == "error"
    assert "tool failed" in chat.sent[1][0][-1]["content"]


@pytest.mark.parametrize("name,args,ok", [
    ("kpi_profile", {"cell_id": "CELL_001", "kpi": "prb_utilization_pct"}, True),
    ("kpi_profile", {"cell_id": "CELL_001; DROP TABLE kpis", "kpi": "k"}, False),
    ("kpi_profile", {"cell_id": "CELL_001"}, False),
    ("kpi_profile", "CELL_001", False),
    ("get_kpis", {"cell_id": "C1", "kpi": "k", "hours": 100000}, True),   # clamped
    ("get_kpis", {"cell_id": "C1", "kpi": "k", "hours": "many"}, False),
    ("search_runbooks", {"query": ""}, False),
    ("search_runbooks", {"query": "x" * 301}, False),
    ("ticket_history", {"cell_id": "C1", "limit": -4}, True),             # clamped
    ("nope", {}, False),
])
def test_argument_validation(name, args, ok):
    cleaned, err = inv.validate_args(name, args)
    assert (err is None) == ok
    if ok and "hours" in (cleaned or {}):
        assert cleaned["hours"] == 168
    if ok and "limit" in (cleaned or {}):
        assert cleaned["limit"] == 1


def test_observations_are_size_capped():
    big = [{"text": "x" * 500}] * 50
    assert len(inv._observation(big)) < inv.MAX_OBSERVATION_CHARS + 50


# ---- the graph: both modes, safety net, and the approval gate --------------------------

@pytest.fixture
def agent(monkeypatch):
    import app.db
    monkeypatch.setattr(app.db, "get_pool", lambda *a, **k: MagicMock())
    from app import agent as a
    return a


def _graph(agent, monkeypatch, mode, investigate_result):
    from langgraph.checkpoint.memory import MemorySaver
    monkeypatch.setattr(agent, "settings", dataclasses.replace(agent.settings, agent_mode=mode))
    created = []
    monkeypatch.setattr(agent.tools, "kpi_profile", lambda *a, **k: {"z": 9, "src": "fixed"})
    monkeypatch.setattr(agent, "retrieve",
                        lambda q, **k: [{"source": "rb.md", "chunk": 0, "text": "steps"}])
    monkeypatch.setattr(agent, "chat", lambda *a, **k: "Diagnosis citing [rb.md#0]")
    monkeypatch.setattr(agent, "investigate", lambda alert: investigate_result)
    monkeypatch.setattr(agent.tools, "create_ticket",
                        lambda *a, **k: created.append(a) or {"id": "INC-1"})
    return agent.build(MemorySaver()), created


def _run(g, approve):
    cfg = {"configurable": {"thread_id": "t1"}}
    g.invoke({"alert": ALERT}, cfg)
    state = g.get_state(cfg)
    assert state.next == ("approval",)  # paused at the human gate in every mode
    return g, cfg, state


def test_agentic_mode_pauses_for_approval_and_creates_nothing_before_it(agent, monkeypatch):
    res = {"profile": {"z": 2}, "runbook": [{"source": "a.md", "chunk": 1, "text": "t"}],
           "history": [], "notes": "n", "trace": [{"tool": "kpi_profile", "outcome": "ok"}],
           "stopped": "done"}
    g, created = _graph(agent, monkeypatch, "agentic", res)
    g, cfg, state = _run(g, True)
    assert created == []
    assert state.values["profile"] == {"z": 2}  # the agent's evidence, not the fixed path's
    from langgraph.types import Command
    g.invoke(Command(resume={"approve": False, "by": "op"}), cfg)
    assert created == []  # declined: still nothing written


def test_approval_is_the_only_path_to_a_ticket(agent, monkeypatch):
    res = {"profile": {"z": 2}, "runbook": [], "history": None, "notes": "", "trace": [],
           "stopped": "done"}
    g, created = _graph(agent, monkeypatch, "agentic", res)
    g, cfg, _ = _run(g, True)
    from langgraph.types import Command
    g.invoke(Command(resume={"approve": True, "by": "alice"}), cfg)
    assert len(created) == 1


def test_safety_net_fills_missing_evidence(agent, monkeypatch):
    res = {"profile": None, "runbook": [], "history": None, "notes": "", "trace": [],
           "stopped": "no_tools"}
    g, _ = _graph(agent, monkeypatch, "agentic", res)
    _, _, state = _run(g, True)
    assert state.values["profile"]["src"] == "fixed" and state.values["runbook"]
    assert {t["outcome"] for t in state.values["trace"]} == {"safety_net"}


def test_tool_calling_failure_falls_back_to_fixed_evidence(agent, monkeypatch):
    g, _ = _graph(agent, monkeypatch, "agentic", None)

    def boom(alert):
        raise RuntimeError("model has no tool support")
    monkeypatch.setattr(agent, "investigate", boom)
    _, _, state = _run(g, True)
    assert state.values["profile"]["src"] == "fixed" and state.values["runbook"]


def test_fixed_mode_does_not_call_the_model_for_tools(agent, monkeypatch):
    g, _ = _graph(agent, monkeypatch, "fixed", None)

    def boom(alert):
        raise AssertionError("investigate must not run in fixed mode")
    monkeypatch.setattr(agent, "investigate", boom)
    _, _, state = _run(g, True)
    assert state.values["profile"]["src"] == "fixed"


def test_tools_are_pinned_to_the_alerted_cell_and_kpi():
    """A model steered by alert text must not fetch another cell's evidence and have it shown
    to the approver as this alert's profile."""
    log = []
    chat = scripted(
        turn(call("kpi_profile", {"cell_id": "CELL_999", "kpi": "prb_utilization_pct"}, 1),
             call("kpi_profile", {"cell_id": "CELL_001", "kpi": "handover_success_rate"}, 2),
             call("ticket_history", {"cell_id": "CELL_999"}, 3),
             call("get_kpis", {"cell_id": "CELL_999", "kpi": "prb_utilization_pct"}, 4)),
        turn(text="done"))
    r = inv.investigate(ALERT, chat, runner(log))
    assert [t["outcome"] for t in r["trace"]] == ["rejected"] * 4
    assert log == [] and r["profile"] is None and r["history"] is None
    assert "alerted cell" in chat.sent[1][0][-1]["content"]
    ok = inv.scope_error("kpi_profile", {"cell_id": "CELL_001", "kpi": "prb_utilization_pct"}, ALERT)
    assert ok is None
    # other KPIs of the SAME cell are legitimate raw-data reads
    assert inv.scope_error("get_kpis", {"cell_id": "CELL_001", "kpi": "handover_success_rate"},
                           ALERT) is None
