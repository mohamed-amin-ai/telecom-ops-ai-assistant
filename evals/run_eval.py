"""Retrieval eval with uncertainty: dense vs hybrid vs hybrid+rerank, per question set.

  python -m evals.run_eval [--k 3] [--out details.json]

Reports, per configuration and per split (standard, hard, all): hit@k with a Wilson interval,
MRR and nDCG@k with bootstrap intervals. Then PAIRED comparisons between adjacent
configurations on the same questions: mean difference in reciprocal rank with a bootstrap
interval, and an exact McNemar p-value on hit@k. 'significant' means the interval excludes
zero for these questions; with the numbers close to ceiling most comparisons will not be.
"""
import argparse
import itertools
import json
from collections.abc import Callable

from evals.stats import (
    bootstrap_ci,
    hit_at_k,
    mcnemar_exact,
    ndcg_at_k,
    paired_bootstrap,
    recall_at_k,
    reciprocal_rank,
    wilson_interval,
)

SETS = [("standard", "evals/golden_set.jsonl"), ("hard", "evals/golden_hard.jsonl")]
CONFIGS = [("dense", False), ("hybrid", False), ("hybrid", True)]


def load(path: str, split: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [{**r, "split": r.get("split", split)} for r in rows if r.get("answerable")]


def evaluate_config(rows: list[dict], mode: str, rerank: bool, k: int,
                    retrieve_fn: Callable) -> list[dict]:
    out = []
    for r in rows:
        ranked = [h["source"] for h in retrieve_fn(r["question"], k=k, mode=mode, rerank=rerank)]
        rel = set(r["expected_sources"])
        out.append({"id": r.get("id", r["question"][:40]), "split": r["split"], "ranked": ranked,
                    "hit": hit_at_k(ranked, rel, k), "rr": reciprocal_rank(ranked, rel),
                    "ndcg": ndcg_at_k(ranked, rel, k), "recall": recall_at_k(ranked, rel, k)})
    return out


def summarize(per_q: list[dict], k: int) -> dict:
    n = len(per_q)
    hits = int(sum(q["hit"] for q in per_q))
    hit_lo, hit_hi = wilson_interval(hits, n)
    mrr_lo, mrr_hi = bootstrap_ci([q["rr"] for q in per_q])
    nd_lo, nd_hi = bootstrap_ci([q["ndcg"] for q in per_q])
    return {"n": n, "k": k, "hit_at_k": round(hits / n, 3), "hit_lo": round(hit_lo, 3),
            "hit_hi": round(hit_hi, 3), "mrr": round(sum(q["rr"] for q in per_q) / n, 3),
            "mrr_lo": round(mrr_lo, 3), "mrr_hi": round(mrr_hi, 3),
            "ndcg": round(sum(q["ndcg"] for q in per_q) / n, 3), "ndcg_lo": round(nd_lo, 3),
            "ndcg_hi": round(nd_hi, 3),
            "recall": round(sum(q["recall"] for q in per_q) / n, 3)}


def compare(a: list[dict], b: list[dict]) -> dict:
    pb = paired_bootstrap([q["rr"] for q in a], [q["rr"] for q in b])
    a_only = sum(1 for x, y in zip(a, b, strict=True) if x["hit"] and not y["hit"])
    b_only = sum(1 for x, y in zip(a, b, strict=True) if y["hit"] and not x["hit"])
    return {"rr_mean_diff": round(pb["mean_diff"], 4), "rr_ci": [round(v, 4) for v in pb["ci"]],
            "rr_significant": pb["significant"], "hit_only_a": a_only, "hit_only_b": b_only,
            "hit_mcnemar_p": round(mcnemar_exact(a_only, b_only), 4)}


def run(k: int, retrieve_fn: Callable, sets=SETS) -> tuple[list[dict], dict]:
    rows = [r for split, path in sets for r in load(path, split)]
    results = {cfg: evaluate_config(rows, *cfg, k, retrieve_fn) for cfg in CONFIGS}
    lines = []
    for split in ("all", *[s for s, _ in sets]):
        for (mode, rerank), per_q in results.items():
            sub = per_q if split == "all" else [q for q in per_q if q["split"] == split]
            if sub:
                lines.append({"kind": "metrics", "split": split, "mode": mode, "rerank": rerank,
                              **summarize(sub, k)})
        for a_cfg, b_cfg in itertools.pairwise(CONFIGS):
            pa, pb = results[a_cfg], results[b_cfg]
            if split != "all":
                pa, pb = ([q for q in x if q["split"] == split] for x in (pa, pb))
            if pa:
                lines.append({"kind": "compare", "split": split,
                              "a": f"{a_cfg[0]}{'+rerank' if a_cfg[1] else ''}",
                              "b": f"{b_cfg[0]}{'+rerank' if b_cfg[1] else ''}", **compare(pa, pb)})
    return lines, results


if __name__ == "__main__":
    from app.rag import retrieve

    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--out", help="write per-question rankings and scores here")
    a = ap.parse_args()
    lines, results = run(a.k, retrieve)
    for line in lines:
        print(json.dumps(line))
    if a.out:
        with open(a.out, "w") as f:
            json.dump({f"{m}{'+rerank' if r else ''}": v for (m, r), v in results.items()}, f)
