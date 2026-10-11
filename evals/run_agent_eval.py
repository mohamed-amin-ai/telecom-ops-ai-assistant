"""End-to-end agent eval: runs real incidents through a running API and scores the agent.

Where run_tool_eval.py scores one model turn, this scores the whole investigation with the real
tools and data, using ground truth we know because we injected it: CELL_001 PRB, CELL_002 RRC and
CELL_003 handover are faulty; the other six cell/KPI pairs are healthy controls. Every pair fires
an alert, so a good agent must say "abnormal" for 3 and "normal" for 6.

  python -m evals.run_agent_eval --url http://localhost:8000 --repeats 3 [--judge] --out agent_eval.json

Metrics (95% Wilson intervals on proportions):
  detection_recall      faulty pairs where the profile flagged the KPI abnormal
  false_alarm_rate      healthy pairs flagged abnormal
  self_kpi_profile /    the MODEL itself called the tool (outcome ok), not the safety net
  self_runbook /
  self_history
  safety_net_share      share of tool calls the deterministic safety net had to fill in
  tool_calls_mean       calls per incident; duplicates/rejected counted separately
  stability             mean pairwise Jaccard of the tool sets across repeats of one pair
  judge (optional, uses JUDGE_MODEL): consistent (diagnosis agrees with the measured profile),
        grounded (numbers it cites appear in the profile), actionable, severity_stated
Caveats: nine pairs are few, so the intervals are wide; the data is seeded synthetic data; the
judge is an LLM (use a different model from the generator when you can); detection comes from the
statistical profile tool, so it tests that the agent got the evidence, not that it reasons well.
"""
import argparse
import itertools
import json
import os
import re
import statistics

from evals.stats import wilson_interval
from scripts.bench_incident import call, percentile
from scripts.seed_kpis import BASE, CELLS, FAULTS

PAIRS = [(c, k) for c in CELLS for k in BASE]
SELF_TOOLS = {"kpi_profile": "self_kpi_profile", "search_runbooks": "self_runbook",
              "ticket_history": "self_history"}

JUDGE_PROMPT = (
    "You grade a network-operations assistant. Measured evidence (JSON) and the assistant's "
    "diagnosis follow. Answer ONLY with a JSON object with four booleans:\n"
    '{"consistent": the diagnosis agrees with the evidence (says abnormal when anomalous is '
    'true, normal/no fault when it is false), "grounded": every number or trend it cites '
    'appears in the evidence, "actionable": it names a concrete next step, '
    '"severity_stated": it states a severity or urgency}\n\n'
    "EVIDENCE:\n{evidence}\n\nDIAGNOSIS:\n{diagnosis}\n")


def rate(vals: list[bool]) -> dict:
    n, k = len(vals), sum(vals)
    lo, hi = wilson_interval(k, n) if n else (0.0, 1.0)
    return {"n": n, "rate": round(k / n, 3) if n else None, "lo": round(lo, 3), "hi": round(hi, 3)}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else 1.0


def parse_judge(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    keys = ("consistent", "grounded", "actionable", "severity_stated")
    return {k: bool(d[k]) for k in keys} if all(k in d for k in keys) else None


def summarize(records: list[dict]) -> dict:
    ok = [r for r in records if r["ok"]]
    faulty = [r for r in ok if r["faulty"]]
    healthy = [r for r in ok if not r["faulty"]]
    out = {
        "runs": {"total": len(records), "ok": len(ok)},
        "detection_recall": rate([bool(r["anomalous"]) for r in faulty]),
        "false_alarm_rate": rate([bool(r["anomalous"]) for r in healthy]),
    }
    for tool, key in SELF_TOOLS.items():
        out[key] = rate([any(t["tool"] == tool and t["outcome"] == "ok" for t in r["tools"])
                         for r in ok])
    calls = [t for r in ok for t in r["tools"]]
    out["safety_net_share"] = round(sum(t["outcome"] == "safety_net" for t in calls) / len(calls),
                                    3) if calls else None
    out["tool_calls_mean"] = round(len(calls) / len(ok), 2) if ok else None
    out["bad_calls"] = {o: sum(t["outcome"] == o for t in calls)
                        for o in ("duplicate", "rejected", "error", "budget")}
    sets = {}
    for r in ok:
        sets.setdefault((r["cell"], r["kpi"]), []).append({t["tool"] for t in r["tools"]})
    pair_scores = [statistics.mean(jaccard(a, b) for a, b in itertools.combinations(v, 2))
                   for v in sets.values() if len(v) > 1]
    out["stability"] = round(statistics.mean(pair_scores), 3) if pair_scores else None
    secs = [r["seconds"] for r in ok]
    out["latency_s"] = {"median": round(statistics.median(secs), 1),
                        "p95": round(percentile(secs, 0.95), 1)} if secs else None
    judged = [r["judge"] for r in ok if r.get("judge")]
    if any("judge" in r for r in ok):
        out["judge"] = {"scored": len(judged),
                        "failed": sum(1 for r in ok if "judge" in r and not r["judge"]),
                        **{k: rate([j[k] for j in judged])
                           for k in ("consistent", "grounded", "actionable", "severity_stated")}}
        # "names a next step" only makes sense where there is a fault: a correct "no fault
        # evident" on a healthy cell has no step to name, so score these two on faulty runs only.
        fj = [r["judge"] for r in faulty if r.get("judge")]
        out["judge"]["actionable_on_faulty"] = rate([j["actionable"] for j in fj])
        out["judge"]["severity_on_faulty"] = rate([j["severity_stated"] for j in fj])
    return out


def judge_one(rec: dict, chat) -> dict | None:
    evidence = json.dumps({"profile": rec["profile"], "faulty_ground_truth_hidden": True},
                          default=str)
    prompt = JUDGE_PROMPT.replace("{evidence}", evidence).replace(
        "{diagnosis}", str(rec["diagnosis"])[:3000])
    try:
        return parse_judge(chat([{"role": "user", "content": prompt}], model=os.getenv("JUDGE_MODEL")))
    except Exception as e:  # noqa: BLE001 -- a judge failure is reported, not fatal
        print(f"judge call failed: {type(e).__name__}: {e}")
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--key", default=os.getenv("API_KEY", ""))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    code, body = call("GET", f"{a.url}/health", key=a.key, timeout=10)
    if code != 200:
        print(f"API not reachable at {a.url}/health ({code}: {str(body)[:120]}); not running the eval.")
        return 2
    chat = None
    if a.judge:
        from app.llm import chat
    import time
    records = []
    for rep in range(a.repeats):
        for cell, kpi in PAIRS:
            t0 = time.perf_counter()
            s, r = call("POST", f"{a.url}/incident",
                        {"cell_id": cell, "kpi": kpi, "description": f"{kpi} alert on {cell}"}, a.key)
            dt = time.perf_counter() - t0
            good = s == 200 and isinstance(r, dict) and r.get("status") == "awaiting_approval"
            rec = {"cell": cell, "kpi": kpi, "faulty": (cell, kpi) in FAULTS, "ok": good,
                   "seconds": round(dt, 2), "tools": [], "anomalous": None, "profile": None,
                   "diagnosis": ""}
            if good:
                call("POST", f"{a.url}/incident/{r['thread_id']}/decision", {"approve": False}, a.key)
                prof = r.get("profile") or {}
                rec.update(tools=r.get("investigation") or [], profile=prof,
                           anomalous=bool(prof.get("anomalous")), diagnosis=r.get("diagnosis") or "")
                if chat:
                    rec["judge"] = judge_one(rec, chat)
            print(f"rep {rep + 1}/{a.repeats} {cell}/{kpi}: {dt:5.1f}s "
                  f"{'ok' if good else f'FAILED ({s})'}", flush=True)
            records.append(rec)
    summary = summarize(records)
    print(json.dumps({"label": a.label, **summary}, indent=2))
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"label": a.label, "summary": summary, "records": records}, f, indent=2,
                      default=str)
    return 0 if summary["runs"]["ok"] == summary["runs"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
