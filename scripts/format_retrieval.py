"""Compact, human-readable table from evals.run_eval JSON lines (stdin) for CI annotations."""
import json
import sys

metrics, compares = [], []
for line in sys.stdin:
    line = line.strip()
    if line.startswith("{"):
        d = json.loads(line)
        (metrics if d["kind"] == "metrics" else compares).append(d)
print(f"{'split':9}{'config':16}{'n':>4}  {'hit@k [95% CI]':24}{'MRR [95% CI]':24}{'nDCG [95% CI]'}")
for m in metrics:
    cfg = m["mode"] + ("+rerank" if m["rerank"] else "")
    print(f"{m['split']:9}{cfg:16}{m['n']:>4}  "
          f"{m['hit_at_k']:.3f} [{m['hit_lo']:.3f},{m['hit_hi']:.3f}]   "
          f"{m['mrr']:.3f} [{m['mrr_lo']:.3f},{m['mrr_hi']:.3f}]   "
          f"{m['ndcg']:.3f} [{m['ndcg_lo']:.3f},{m['ndcg_hi']:.3f}]")
print("\npaired comparisons (same questions; 'significant' = RR-difference interval excludes 0):")
for c in compares:
    print(f"{c['split']:9}{c['a']:>16} -> {c['b']:<16} dRR={c['rr_mean_diff']:+.4f} {c['rr_ci']} "
          f"{'SIGNIFICANT' if c['rr_significant'] else 'not significant'}; "
          f"hit only-a/only-b={c['hit_only_a']}/{c['hit_only_b']} McNemar p={c['hit_mcnemar_p']}")
