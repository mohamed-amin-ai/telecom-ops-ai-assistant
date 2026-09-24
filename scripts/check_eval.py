"""Fail if retrieval metrics fall below a floor. Reads run_eval JSON lines on stdin.
Usage: python -m evals.run_eval | python scripts/check_eval.py --min-hit 0.8 --min-mrr 0.6"""
import argparse
import json
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--min-hit", type=float, default=0.0)
ap.add_argument("--min-mrr", type=float, default=0.0)
a = ap.parse_args()
bad = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    m = json.loads(line)
    print(line)
    if m["hit@k"] < a.min_hit or m["mrr"] < a.min_mrr:
        bad.append(f'{m["mode"]} rerank={m["rerank"]}: hit@k={m["hit@k"]} mrr={m["mrr"]}')
if bad:
    print("BELOW FLOOR:", *bad, sep="\n  ")
    sys.exit(1)
