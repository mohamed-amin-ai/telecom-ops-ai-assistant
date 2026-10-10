"""Tool-selection accuracy for the investigation agent.

  python -m evals.run_tool_eval [--set evals/tool_selection_set.jsonl] [--model MODEL]

One model turn per scenario with the real tool specs (nothing is executed). Scored:
  first_tool   the first tool called is acceptable for the scenario (or, where no tool is
               needed, the model called none)
  args         when the right tool was chosen: the arguments carry the expected values
               (cell, KPI, hours) and pass the same validation the agent applies
  no_write     the model never named a write tool (none is offered; naming one means it
               would write if it could)
  valid        every call it made passes validate_args
Reported with 95% Wilson intervals, overall and per category. The set is the author's own
scenarios (not drawn from real NOC traffic), so read the numbers as a regression check and a
model comparison, not as production accuracy.
"""
import argparse
import json
from collections import defaultdict

from app.investigator import SYSTEM, TOOL_SPECS, validate_args
from evals.stats import wilson_interval


def messages_for(row: dict) -> list[dict]:
    text = f"Alert: {row['input']}" if isinstance(row["input"], dict) else row["input"]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]


def score_row(row: dict, resp: dict) -> dict:
    calls = resp["tool_calls"]
    first = calls[0]["name"] if calls else "NONE"
    first_ok = first in row["accept_first"] and (not row["expect_no_tool"] or not calls)
    args_ok = None
    exp = row["args_expect"].get(first)
    if first_ok and exp:
        got = calls[0]["arguments"] or {}
        cleaned, err = validate_args(first, got)
        args_ok = err is None and all(
            str(cleaned.get(k, got.get(k))).lower() == str(v).lower() for k, v in exp.items())
    return {"id": row["id"], "category": row["category"], "first": first, "first_ok": first_ok,
            "args_ok": args_ok,
            "no_write": not any(c["name"] in row["forbid"] for c in calls),
            "valid": all(validate_args(c["name"], c["arguments"])[1] is None for c in calls
                         if c["name"] in {t["function"]["name"] for t in TOOL_SPECS})}


def _rate(vals: list[bool]) -> dict:
    n, k = len(vals), sum(vals)
    lo, hi = wilson_interval(k, n) if n else (0.0, 0.0)
    return {"n": n, "rate": round(k / n, 3) if n else None, "lo": round(lo, 3),
            "hi": round(hi, 3)}


def summarize(scored: list[dict]) -> dict:
    out = {"overall": {
        "first_tool": _rate([s["first_ok"] for s in scored]),
        "args": _rate([s["args_ok"] for s in scored if s["args_ok"] is not None]),
        "no_write": _rate([s["no_write"] for s in scored]),
        "valid": _rate([s["valid"] for s in scored])}}
    by = defaultdict(list)
    for s in scored:
        by[s["category"]].append(s["first_ok"])
    out["first_tool_by_category"] = {c: _rate(v) for c, v in sorted(by.items())}
    out["wrong"] = [{"id": s["id"], "category": s["category"], "called": s["first"]}
                    for s in scored if not s["first_ok"]]
    return out


def run(rows: list[dict], chat_fn, model: str | None = None) -> dict:
    scored = []
    for r in rows:
        try:
            resp = chat_fn(messages_for(r), TOOL_SPECS, model) if model else \
                chat_fn(messages_for(r), TOOL_SPECS)
        except Exception as e:  # noqa: BLE001 -- a failed call is a wrong answer, not a crash
            resp = {"content": f"ERROR {type(e).__name__}", "tool_calls": []}
            print(f"call failed for {r['id']}: {type(e).__name__}: {e}")
        scored.append(score_row(r, resp))
    return summarize(scored)


if __name__ == "__main__":
    from app.llm import chat_with_tools

    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="evals/tool_selection_set.jsonl")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    with open(a.set, encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    print(json.dumps(run(rows, chat_with_tools, a.model)))
