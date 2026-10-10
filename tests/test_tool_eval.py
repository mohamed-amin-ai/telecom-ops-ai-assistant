import json
from pathlib import Path

from app.investigator import TOOL_NAMES
from evals import run_tool_eval as ev

ROWS = [json.loads(x) for x in
        (Path(__file__).resolve().parent.parent / "evals/tool_selection_set.jsonl")
        .read_text(encoding="utf-8").splitlines() if x.strip()]


def oracle(messages, tools, *_):
    """Answers every scenario correctly from its own labels: the eval must score it 100%."""
    row = next(r for r in ROWS if (f"Alert: {r['input']}" if isinstance(r["input"], dict)
                                   else r["input"]) == messages[1]["content"])
    if row["expect_no_tool"]:
        return {"content": "ok", "tool_calls": []}
    tool = next(t for t in row["accept_first"] if t != "NONE")
    args = row["args_expect"].get(tool) or {
        "kpi_profile": {"cell_id": "C1", "kpi": "k"}, "get_kpis": {"cell_id": "C1", "kpi": "k"},
        "ticket_history": {"cell_id": "C1"}, "search_runbooks": {"query": "q"}}[tool]
    return {"content": "", "tool_calls": [{"id": "1", "name": tool, "arguments": args}]}


def test_dataset_is_well_formed_and_covers_every_tool():
    ids = [r["id"] for r in ROWS]
    assert len(ids) == len(set(ids)) >= 40
    wanted = {t for r in ROWS for t in r["accept_first"]} - {"NONE"}
    assert wanted == TOOL_NAMES  # every tool is the right answer somewhere
    cats = {r["category"] for r in ROWS}
    assert {"alert_triage", "raw_series", "history", "knowledge", "write_request",
            "no_tool", "anomaly_check"} <= cats
    for r in ROWS:
        assert set(r["args_expect"]) <= TOOL_NAMES
        assert "create_ticket" in r["forbid"]


def test_oracle_scores_perfectly():
    s = ev.run(ROWS, oracle)
    assert s["overall"]["first_tool"]["rate"] == 1.0 and s["overall"]["args"]["rate"] == 1.0
    assert s["overall"]["no_write"]["rate"] == 1.0 and s["wrong"] == []


def test_always_wrong_and_writing_models_are_penalised():
    def writer(m, t, *_):
        return {"content": "", "tool_calls": [
            {"id": "1", "name": "create_ticket", "arguments": {"cell_id": "CELL_001"}}]}
    s = ev.run(ROWS, writer)
    assert s["overall"]["first_tool"]["rate"] == 0.0
    assert s["overall"]["no_write"]["rate"] == 0.0 and s["overall"]["valid"]["rate"] == 1.0


def test_wrong_arguments_fail_args_but_not_first_tool():
    def wrong_cell(m, t, *_):
        r = oracle(m, t)
        for c in r["tool_calls"]:
            if "cell_id" in c["arguments"]:
                c["arguments"] = {**c["arguments"], "cell_id": "CELL_999"}
        return r
    s = ev.run(ROWS, wrong_cell)
    assert s["overall"]["first_tool"]["rate"] == 1.0
    assert s["overall"]["args"]["rate"] < 0.5


def test_a_call_that_raises_counts_as_wrong_not_a_crash():
    def broken(m, t, *_):
        raise RuntimeError("provider down")
    s = ev.run(ROWS, broken)
    assert s["overall"]["first_tool"]["n"] == len(ROWS)
    assert s["overall"]["first_tool"]["rate"] < 0.25  # only the no-tool and write rows "pass"
