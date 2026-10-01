"""Red-team the guardrails. Reports attack detection and false-positive rate per split.

  python -m evals.run_redteam            # deterministic rule layer only (fast, no LLM)
  python -m evals.run_redteam --llm      # also run the LLM classifier (needs a model; cases
                                         # marked requires_llm are only scored with this flag)

Splits: 'dev' is what the rules were tuned against, so its numbers are optimistic.
'heldout' was written before the last rule change and is the honest estimate -- but once you
tune against it, it stops being held out. Write new held-out cases before trusting a number."""
import argparse
import json
import os
import sys
from collections import defaultdict


def main(path: str, use_llm: bool) -> int:
    os.environ["GUARD_LLM"] = "1" if use_llm else "0"
    from app.guardrails import check_input

    with open(path, encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]
    stats = defaultdict(lambda: {"attack": [0, 0], "benign": [0, 0]})
    misses = []
    for c in cases:
        if c["requires_llm"] and not use_llm:
            continue
        blocked = not check_input(c["text"], kind="question").allowed
        kind = "attack" if c["expected"] == "block" else "benign"
        ok = blocked == (kind == "attack")
        stats[c["split"]][kind][0] += ok
        stats[c["split"]][kind][1] += 1
        if not ok:
            misses.append((c["split"], c["id"], c["category"], kind, c["text"][:80]))
    for split, s in stats.items():
        a, b = s["attack"], s["benign"]
        print(json.dumps({
            "split": split, "llm": use_llm,
            "attack_detection": f"{a[0]}/{a[1]}", "attack_rate": round(a[0] / max(a[1], 1), 3),
            "benign_allowed": f"{b[0]}/{b[1]}", "false_positive_rate": round(1 - b[0] / max(b[1], 1), 3),
        }))
    for m in misses:
        print("MISS", *m)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="evals/redteam_set.jsonl")
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.path, a.llm))
