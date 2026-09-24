"""End-to-end generation eval with an LLM judge (correctness, faithfulness, abstention).
Run:  python -m evals.run_gen_eval [path] [--limit N] [--min-pass X] [--min-faithful X]
--limit N samples N answerable questions plus a few unanswerable ones.
Uses the configured retrieval settings (RETRIEVAL_MODE / RERANK) and JUDGE_MODEL."""
import argparse
import json
import re
import sys

from app.config import settings
from app.llm import chat
from app.rag import answer

JUDGE = (
    "You grade a RAG answer. Return ONLY a JSON object with boolean fields "
    '"correct", "faithful", "abstained".\n'
    "correct: the answer states the key facts of the reference without contradicting it.\n"
    "faithful: every factual claim in the answer is supported by the context.\n"
    "abstained: the answer says the documentation/context does not cover the question."
)


def judge(question: str, reference: str, ans: str, contexts: list[str]) -> dict:
    msg = (f"Question: {question}\nReference: {reference}\nAnswer: {ans}\n\n"
           "Context:\n" + "\n---\n".join(contexts))
    raw = chat([{"role": "system", "content": JUDGE}, {"role": "user", "content": msg}],
               model=settings.judge_model)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def main(path: str, limit: int | None, min_pass: float, min_faithful: float) -> None:
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if limit:
        ans = [r for r in rows if r["answerable"]]
        una = [r for r in rows if not r["answerable"]]
        step = max(1, len(ans) // limit)
        rows = ans[::step][:limit] + una[: max(3, limit // 6)]
    ok = faithful = 0
    n_ans = n_unans = 0
    failures = []
    for r in rows:
        out = answer(r["question"])
        j = judge(r["question"], r["reference"], out["answer"], out["contexts"])
        faithful += bool(j.get("faithful"))
        if r["answerable"]:
            n_ans += 1
            good = bool(j.get("correct"))
        else:
            n_unans += 1
            good = bool(j.get("abstained"))
        ok += good
        if not good:
            failures.append({"id": r["id"], "question": r["question"], "answer": out["answer"]})
    pass_rate, faith = ok / len(rows), faithful / len(rows)
    print(json.dumps({
        "n": len(rows), "answerable": n_ans, "unanswerable": n_unans,
        "pass_rate": round(pass_rate, 3),
        "faithfulness": round(faith, 3),
        "retrieval_mode": settings.retrieval_mode, "rerank": settings.rerank,
        "llm": settings.llm_model, "judge": settings.judge_model,
    }))
    with open("evals/last_failures.json", "w") as f:
        json.dump(failures, f, indent=2)
    print(f"{len(failures)} failures written to evals/last_failures.json")
    if pass_rate < min_pass or faith < min_faithful:
        print(f"BELOW FLOOR (min-pass {min_pass}, min-faithful {min_faithful})")
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="evals/golden_set.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-pass", type=float, default=0.0)
    ap.add_argument("--min-faithful", type=float, default=0.0)
    a = ap.parse_args()
    main(a.path, a.limit, a.min_pass, a.min_faithful)
