"""Pool per-question RAGAS scores from parallel shards and report means with intervals.

  python -m evals.aggregate_ragas shard0.json shard1.json ... [--min-scored 0.5]

Reports, per metric: how many questions were scored, how many failed to parse (NaN) -- those
are excluded from the mean and counted, never silently treated as 0 or 1 -- the mean, and a
bootstrap interval. Also broken down by question set (standard vs hard). Fails if a metric
has no scored rows at all, or if fewer than --min-scored of its rows were scored: a mean over
the lucky 20% of rows that parsed isn't a measurement of the other 80%.
"""
import argparse
import json
import sys

from evals.stats import bootstrap_ci

METRICS = ["faithfulness", "answer_relevancy", "llm_context_precision_with_reference",
           "context_recall"]


def summarize(rows: list[dict]) -> dict:
    out = {"n": len(rows)}
    for m in METRICS:
        vals = [r[m] for r in rows if r.get(m) is not None]
        entry = {"scored": len(vals), "failed": len(rows) - len(vals)}
        if vals:
            lo, hi = bootstrap_ci(vals)
            entry |= {"mean": round(sum(vals) / len(vals), 3), "lo": round(lo, 3), "hi": round(hi, 3)}
        out[m] = entry
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--min-scored", type=float, default=0.5)
    a = ap.parse_args()
    rows = []
    for f in a.files:
        with open(f) as fh:
            rows += json.load(fh)
    result = {"judges": sorted({r.get("judge") for r in rows}), "all": summarize(rows)}
    for split in sorted({r["split"] for r in rows}):
        result[split] = summarize([r for r in rows if r["split"] == split])
    print(json.dumps(result, indent=1))
    bad = []
    for m in METRICS:
        e = result["all"][m]
        if e["scored"] == 0:
            bad.append(f"{m}: no row could be scored")
        elif e["scored"] / result["all"]["n"] < a.min_scored:
            bad.append(f"{m}: only {e['scored']}/{result['all']['n']} rows scored")
    if bad:
        print("INSUFFICIENT:", *bad, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
