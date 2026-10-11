"""Time the assistant on incidents: request sent -> 'awaiting approval' (diagnosis drafted).

Run it against any running API (Docker stack, Kaggle, a laptop). The first --warmup runs per
scenario are discarded (model load, embedding model, MCP server start). Each incident is then
rejected so no tickets are created and the database stays clean.

  python scripts/bench_incident.py --url http://localhost:8000 --runs 10 \
      --label "2x T4, vLLM TP=2, Qwen2.5-7B-Instruct" --out bench.json

Reports median / p95 / min / max per scenario and overall, and how the agent behaved (tools
the model chose, how often the deterministic safety net had to fill in). Stdlib only.
"""
import argparse
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.request

SCENARIOS = [
    ("CELL_001", "prb_utilization_pct", "PRB utilization spike on CELL_001"),
    ("CELL_002", "rrc_setup_success_rate", "RRC setup success rate dropped on CELL_002"),
    ("CELL_003", "handover_success_rate", "Handover success rate dropped on CELL_003"),
]


def percentile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    k = max(0, math.ceil(q * len(s)) - 1)  # nearest-rank
    return s[k]


def summarize(rows: list[dict]) -> dict:
    """rows: [{scenario, seconds, status, tools:[{tool,outcome}], ok}]"""
    def stats(sub):
        t = [r["seconds"] for r in sub if r["ok"]]
        return {"n": len(sub), "ok": len(t),
                "median_s": round(statistics.median(t), 2) if t else None,
                "p95_s": round(percentile(t, 0.95), 2) if t else None,
                "min_s": round(min(t), 2) if t else None,
                "max_s": round(max(t), 2) if t else None}
    out = {"overall": stats(rows), "by_scenario": {}}
    for sc in sorted({r["scenario"] for r in rows}):
        out["by_scenario"][sc] = stats([r for r in rows if r["scenario"] == sc])
    good = [r for r in rows if r["ok"]]
    calls = [t for r in good for t in r["tools"]]
    out["agent"] = {
        "tool_calls_per_incident": round(len(calls) / len(good), 2) if good else None,
        "safety_net_share": round(sum(t["outcome"] == "safety_net" for t in calls) / len(calls), 3)
        if calls else None,
        "tool_counts": {n: sum(t["tool"] == n for t in calls)
                        for n in sorted({t["tool"] for t in calls})},
    }
    return out


def call(method, url, body=None, key="", timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **({"X-API-Key": key} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, str(e)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--key", default=os.getenv("API_KEY", ""))
    ap.add_argument("--runs", type=int, default=10, help="timed runs per scenario")
    ap.add_argument("--warmup", type=int, default=1, help="discarded runs per scenario")
    ap.add_argument("--label", default="", help="what this ran on, saved in the output")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)

    code, body = call("GET", f"{a.url}/health", key=a.key, timeout=10)
    if code != 200:
        print(f"API not reachable at {a.url}/health ({code}: {str(body)[:120]}); not running the benchmark.")
        return 2

    rows = []
    for i in range(a.warmup + a.runs):
        for cell, kpi, desc in SCENARIOS:
            t0 = time.perf_counter()
            s, r = call("POST", f"{a.url}/incident",
                        {"cell_id": cell, "kpi": kpi, "description": desc}, a.key)
            dt = time.perf_counter() - t0
            ok = s == 200 and isinstance(r, dict) and r.get("status") == "awaiting_approval"
            if ok:
                call("POST", f"{a.url}/incident/{r['thread_id']}/decision", {"approve": False}, a.key)
            tag = "warmup" if i < a.warmup else "run"
            print(f"{tag} {i + 1}/{a.warmup + a.runs} {cell}: {dt:6.1f}s "
                  f"{'ok' if ok else f'FAILED ({s}: {str(r)[:120]})'}", flush=True)
            if i >= a.warmup:
                rows.append({"scenario": cell, "seconds": round(dt, 3), "ok": ok,
                             "status": s, "tools": (r.get("investigation") or []) if ok else []})
    summary = summarize(rows)
    result = {"label": a.label, "runs_per_scenario": a.runs, "warmup": a.warmup,
              "summary": summary, "rows": rows}
    print(json.dumps({"label": a.label, **summary}, indent=2))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(result, f, indent=2)
    return 0 if summary["overall"]["ok"] == summary["overall"]["n"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
