"""End-to-end generation eval with an LLM judge (correctness, faithfulness, abstention).
Run:  python -m evals.run_gen_eval [path/to/golden.jsonl] [limit]
Uses the configured retrieval settings (RETRIEVAL_MODE / RERANK) and JUDGE_MODEL."""
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


def main(path: str, limit: int | None) -> None:
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    rows = rows[:limit] if limit else rows
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
    print(json.dumps({
        "n": len(rows), "answerable": n_ans, "unanswerable": n_unans,
        "pass_rate": round(ok / len(rows), 3),
        "faithfulness": round(faithful / len(rows), 3),
        "retrieval_mode": settings.retrieval_mode, "rerank": settings.rerank,
        "llm": settings.llm_model, "judge": settings.judge_model,
    }))
    with open("evals/last_failures.json", "w") as f:
        json.dump(failures, f, indent=2)
    print(f"{len(failures)} failures written to evals/last_failures.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "evals/golden_set.jsonl",
         int(sys.argv[2]) if len(sys.argv) > 2 else None)
