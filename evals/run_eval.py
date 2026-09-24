"""Retrieval ablation: dense vs hybrid vs hybrid+rerank on the answerable golden questions.
Run:  python -m evals.run_eval [path/to/golden.jsonl] [k]"""
import json
import sys

from app.rag import retrieve


def load(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def run(rows: list[dict], mode: str, rerank: bool, k: int) -> dict:
    hit = rr = recall = 0.0
    for r in rows:
        srcs = [h["source"] for h in retrieve(r["question"], k=k, mode=mode, rerank=rerank)]
        exp = set(r["expected_sources"])
        ranks = [i for i, s in enumerate(srcs, 1) if s in exp]
        hit += bool(ranks)
        rr += 1 / ranks[0] if ranks else 0
        recall += len(exp & set(srcs)) / len(exp)
    n = len(rows)
    return {"mode": mode, "rerank": rerank, "k": k, "n": n,
            "hit@k": round(hit / n, 3), "mrr": round(rr / n, 3),
            "recall@k": round(recall / n, 3)}


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "evals/golden_set.jsonl"
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    rows = [r for r in load(path) if r["answerable"]]
    for mode, rerank in [("dense", False), ("hybrid", False), ("hybrid", True)]:
        print(json.dumps(run(rows, mode, rerank, k)))
