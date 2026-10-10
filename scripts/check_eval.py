"""Fail if a retrieval metric's LOWER confidence bound falls below a floor. Gating on the
point estimate lets a lucky run pass and an unlucky one fail for no real reason; the lower
bound only fails when we are reasonably sure the true value is below the floor.
Reads run_eval JSON lines on stdin.
  python -m evals.run_eval | python scripts/check_eval.py --split standard --min-hit-lo 0.9 --min-mrr-lo 0.9"""
import argparse
import json
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--split", default="all")
ap.add_argument("--min-hit-lo", type=float, default=0.0)
ap.add_argument("--min-mrr-lo", type=float, default=0.0)
ap.add_argument("--min-ndcg-lo", type=float, default=0.0)
a = ap.parse_args()
bad = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    print(line)
    m = json.loads(line)
    if m.get("kind") != "metrics" or m["split"] != a.split:
        continue
    name = f'{m["mode"]}{"+rerank" if m["rerank"] else ""}'
    for key, floor in (("hit_lo", a.min_hit_lo), ("mrr_lo", a.min_mrr_lo), ("ndcg_lo", a.min_ndcg_lo)):
        if m[key] < floor:
            bad.append(f"{a.split}/{name}: {key}={m[key]} < {floor}")
if bad:
    print("BELOW FLOOR:", *bad, sep="\n  ")
    sys.exit(1)
