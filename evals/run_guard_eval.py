"""Guardrail eval: does check_input block what it should and allow what it should?
Run:  python -m evals.run_guard_eval [path]      (GUARD_LLM=0 skips LLM-only cases)"""
import json
import sys
from collections import defaultdict

from app.config import settings
from app.guardrails import check_input


def main(path: str) -> None:
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    stats = defaultdict(lambda: [0, 0])  # category -> [correct, total]
    wrong = []
    skipped = 0
    for r in rows:
        if r["requires_llm"] and not settings.guard_llm:
            skipped += 1
            continue
        v = check_input(r["text"], kind=r["kind"])
        ok = v.allowed == (r["expected"] == "allow") and set(r["expect_redactions"]) <= set(v.redactions)
        stats[r["category"]][0] += ok
        stats[r["category"]][1] += 1
        if not ok:
            wrong.append({"id": r["id"], "text": r["text"], "expected": r["expected"],
                          "got": "allow" if v.allowed else v.label, "redactions": v.redactions})
    total = sum(t for _, t in stats.values())
    correct = sum(c for c, _ in stats.values())
    print(json.dumps({"guard_llm": settings.guard_llm, "n": total, "skipped": skipped,
                      "accuracy": round(correct / total, 3),
                      "by_category": {k: f"{c}/{t}" for k, (c, t) in stats.items()}}))
    for w in wrong:
        print("MISS", json.dumps(w))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "evals/guardrail_set.jsonl")
