"""Build a chunk-level retrieval set from the INGESTED 3GPP corpus.

For a seeded sample of real prose chunks (not tables/ASN.1/boilerplate) a local LLM writes one
question an ops engineer could ask whose answer is in that chunk. Gold = that chunk (plus any
chunk with identical body text). Questions that copy a 5-word phrase from the passage are
rejected, so retrieval can't win on verbatim overlap alone.

Honest limits: the questions come from a small model and the gold is "the chunk it was made
from"; neighbouring chunks may also answer, so scores are a LOWER bound, and wording quality
varies. It is not a human-judged benchmark.

  python -m evals.build_3gpp_set --n 60 --out golden_3gpp.jsonl
"""
import argparse
import json
import random
import re
from collections import defaultdict

GENERIC = re.compile(r"^\W*(foreword|scope|references|definitions?|abbreviations?|introduction|"
                     r"change history|annex)\b", re.IGNORECASE)


def body_of(text: str) -> str:
    """Chunk text without the '# 3GPP TS ...' title prefix line."""
    lines = text.splitlines()
    return "\n".join(lines[1:]).strip() if lines and lines[0].startswith("# ") else text.strip()


def is_prose(text: str, lo: int = 500, hi: int = 1250) -> bool:
    body = body_of(text)
    if not lo <= len(body) <= hi:
        return False
    if body.count("|") > 6 or body.count("{") + body.count("}") > 4:  # tables, ASN.1
        return False
    letters = sum(c.isalpha() or c.isspace() for c in body)
    first = re.sub(r"^[#\s\d.]+", "", body.splitlines()[0]) if body else ""  # drop '## 1.2 '
    return letters / len(body) > 0.85 and not GENERIC.match(first)


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def copies_passage(question: str, passage: str, n: int = 5) -> bool:
    q, p = _words(question), " ".join(_words(passage))
    return any(" ".join(q[i:i + n]) in p for i in range(len(q) - n + 1))


def valid_question(q: str, passage: str) -> bool:
    q = q.strip()
    return (30 <= len(q) <= 240 and q.endswith("?") and "\n" not in q
            and not re.search(r"\b(passage|document|text above|the excerpt)\b", q, re.IGNORECASE)
            and not copies_passage(q, passage))


def sample_chunks(payloads: list[dict], n: int, per_spec: int, seed: int = 13) -> list[dict]:
    by_src = defaultdict(list)
    for p in payloads:
        if p["source"].startswith("TS_") and is_prose(p["text"]):
            by_src[p["source"]].append(p)
    rng = random.Random(seed)
    picked = []
    for src in sorted(by_src):
        pool = sorted(by_src[src], key=lambda p: p["chunk"])
        rng.shuffle(pool)
        picked += pool[:per_spec]
    rng.shuffle(picked)
    return picked[:n]


def gold_ids(chunk: dict, payloads: list[dict]) -> list[str]:
    body = body_of(chunk["text"])
    return sorted({f"{p['source']}#{p['chunk']}" for p in payloads if body_of(p["text"]) == body}
                  | {f"{chunk['source']}#{chunk['chunk']}"})


PROMPT = (
    "You write test questions for a retrieval benchmark.\n\nPassage from 3GPP {spec}:\n"
    "\"\"\"\n{body}\n\"\"\"\n\nWrite ONE question that a mobile-network operations engineer might "
    "ask, answerable from this passage alone. Use your own words: do not copy any phrase of "
    "five or more words. Do not mention 'passage' or 'document'. Output only the question.")


def generate(chat, payloads: list[dict], n: int, per_spec: int, seed: int = 13) -> list[dict]:
    rows, tried = [], 0
    for ch in sample_chunks(payloads, n * 2, per_spec, seed):  # oversample: some get rejected
        if len(rows) >= n:
            break
        tried += 1
        spec = re.match(r"TS_(\d+)_(\d+)", ch["source"])
        body = body_of(ch["text"])
        q = chat([{"role": "user", "content": PROMPT.format(
            spec=f"TS {spec.group(1)}.{spec.group(2)}" if spec else ch["source"], body=body)}],
            temperature=0, max_tokens=80).strip().strip('"').splitlines()[0]
        if valid_question(q, body):
            rows.append({"id": f"s{len(rows) + 1:03d}", "question": q, "split": ch["source"],
                         "gold": gold_ids(ch, payloads), "answerable": True,
                         "method": "llm-from-chunk"})
    print(f"kept {len(rows)} of {tried} generated questions")
    return rows


def all_payloads() -> list[dict]:
    from app.config import settings
    from app.rag import _client

    out, offset = [], None
    while True:
        pts, offset = _client().scroll(settings.collection, limit=512, offset=offset,
                                       with_payload=True, with_vectors=False)
        out += [p.payload for p in pts]
        if offset is None:
            return out


if __name__ == "__main__":
    from app.llm import chat

    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--per-spec", type=int, default=10)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out", default="golden_3gpp.jsonl")
    a = ap.parse_args()
    rows = generate(chat, all_payloads(), a.n, a.per_spec, a.seed)
    with open(a.out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
