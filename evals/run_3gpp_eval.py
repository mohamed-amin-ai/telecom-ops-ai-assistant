"""Chunk-level retrieval eval on the 3GPP set built by evals.build_3gpp_set.

  python -m evals.run_3gpp_eval --set golden_3gpp.jsonl [--k 5]

Same configs and statistics as evals.run_eval (hit@k with Wilson interval, MRR/nDCG with
bootstrap intervals, paired comparisons), but ranks are CHUNK ids (source#chunk) so the
retriever must find the right passage, not just the right spec. Split = spec file."""
import argparse
import itertools
import json

from evals.run_eval import CONFIGS, compare, summarize
from evals.stats import hit_at_k, ndcg_at_k, recall_at_k, reciprocal_rank


def evaluate(rows, mode, rerank, k, retrieve_fn):
    out = []
    for r in rows:
        ranked = [f"{h['source']}#{h['chunk']}"
                  for h in retrieve_fn(r["question"], k=k, mode=mode, rerank=rerank)]
        rel = set(r["gold"])
        out.append({"id": r["id"], "split": r["split"], "ranked": ranked,
                    "hit": hit_at_k(ranked, rel, k), "rr": reciprocal_rank(ranked, rel),
                    "ndcg": ndcg_at_k(ranked, rel, k), "recall": recall_at_k(ranked, rel, k)})
    return out


def run(rows, k, retrieve_fn):
    res = {cfg: evaluate(rows, *cfg, k, retrieve_fn) for cfg in CONFIGS}
    lines = []
    for (mode, rerank), per_q in res.items():
        lines.append({"kind": "metrics", "split": "all", "mode": mode, "rerank": rerank,
                      **summarize(per_q, k)})
    for a, b in itertools.pairwise(CONFIGS):
        lines.append({"kind": "compare", "split": "all",
                      "a": f"{a[0]}{'+rerank' if a[1] else ''}",
                      "b": f"{b[0]}{'+rerank' if b[1] else ''}", **compare(res[a], res[b])})
    # per-spec hit@k for the best-known config (hybrid), to show where it is weak
    per_spec = {}
    for q in res[("hybrid", False)]:
        per_spec.setdefault(q["split"], []).append(q["hit"])
    lines.append({"kind": "per_spec_hybrid_hit", "k": k,
                  "specs": {s: {"n": len(v), "hit": round(sum(v) / len(v), 3)}
                            for s, v in sorted(per_spec.items())}})
    return lines


if __name__ == "__main__":
    from app.rag import retrieve

    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="golden_3gpp.jsonl")
    ap.add_argument("--k", type=int, default=5)
    a = ap.parse_args()
    with open(a.set, encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    for line in run(rows, a.k, retrieve):
        print(json.dumps(line))
