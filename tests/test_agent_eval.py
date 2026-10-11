from evals.run_agent_eval import PAIRS, jaccard, parse_judge, summarize
from scripts.seed_kpis import FAULTS


def rec(cell, kpi, anomalous, tools, seconds=10.0, judge=None, ok=True):
    r = {"cell": cell, "kpi": kpi, "faulty": (cell, kpi) in FAULTS, "ok": ok, "seconds": seconds,
         "anomalous": anomalous, "tools": [{"tool": t, "outcome": o} for t, o in tools],
         "profile": {}, "diagnosis": ""}
    if judge is not None:
        r["judge"] = judge
    return r


def test_pairs_cover_three_faults_and_six_controls():
    assert len(PAIRS) == 9 and sum(p in FAULTS for p in PAIRS) == 3


def test_detection_and_tool_metrics():
    full = [("kpi_profile", "ok"), ("search_runbooks", "ok"), ("ticket_history", "ok")]
    net = [("get_kpis", "ok"), ("search_runbooks", "ok"), ("kpi_profile", "safety_net")]
    s = summarize([
        rec("CELL_001", "prb_utilization_pct", True, full),
        rec("CELL_002", "rrc_setup_success_rate", False, net),      # missed fault
        rec("CELL_001", "handover_success_rate", True, net),         # false alarm
        rec("CELL_001", "rrc_setup_success_rate", False, full),
        rec("CELL_003", "handover_success_rate", True, full, ok=False),  # failed run ignored
    ])
    assert s["runs"] == {"total": 5, "ok": 4}
    assert s["detection_recall"]["n"] == 2 and s["detection_recall"]["rate"] == 0.5
    assert s["false_alarm_rate"]["n"] == 2 and s["false_alarm_rate"]["rate"] == 0.5
    assert s["self_kpi_profile"]["rate"] == 0.5          # safety-net kpi_profile does not count
    assert s["safety_net_share"] == round(2 / 12, 3)


def test_stability_and_judge():
    t1 = [("kpi_profile", "ok"), ("search_runbooks", "ok")]
    t2 = [("kpi_profile", "ok")]
    j = {"consistent": True, "grounded": False, "actionable": True, "severity_stated": True}
    failed = rec("CELL_001", "prb_utilization_pct", True, t2)
    failed["judge"] = None        # what the runner stores when the judge call or parse fails
    s = summarize([rec("CELL_001", "prb_utilization_pct", True, t1, judge=j), failed])
    assert s["stability"] == 0.5 and jaccard({"a"}, {"a"}) == 1.0
    assert s["judge"]["scored"] == 1 and s["judge"]["failed"] == 1
    assert s["judge"]["grounded"]["rate"] == 0.0


def test_parse_judge_is_strict():
    ok = '```json\n{"consistent": true, "grounded": true, "actionable": false, "severity_stated": true}\n```'
    assert parse_judge(ok)["actionable"] is False
    assert parse_judge('{"consistent": true}') is None
    assert parse_judge("no json") is None


def test_actionable_is_also_scored_on_faulty_runs_only():
    t = [{"tool": "kpi_profile", "outcome": "ok"}]
    yes = {"consistent": True, "grounded": True, "actionable": True, "severity_stated": True}
    no = {**yes, "actionable": False, "severity_stated": False}
    faulty = rec("CELL_001", "prb_utilization_pct", True, t, judge=yes)
    healthy = rec("CELL_002", "prb_utilization_pct", False, t, judge=no)
    s = summarize([faulty, healthy])
    assert s["judge"]["actionable"]["rate"] == 0.5
    assert s["judge"]["actionable_on_faulty"] == {"n": 1, "rate": 1.0, "lo": s["judge"]["actionable_on_faulty"]["lo"], "hi": 1.0}
    assert s["judge"]["severity_on_faulty"]["n"] == 1
