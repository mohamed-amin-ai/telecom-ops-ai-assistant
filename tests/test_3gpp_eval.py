from evals import build_3gpp_set as b
from evals import run_3gpp_eval as e

PASSAGE = ("# 3GPP TS 28.552 Rel-18 v18.12.0 (u)\n## 5.1.1.2 Average DL UE throughput\n"
           "This measurement provides the average downlink UE throughput in the gNB for each "
           "network slice and it is calculated by the gNB over the measurement period. "
           "The measurement is obtained by dividing the volume by the active time. " * 2)


def test_is_prose_rejects_tables_asn1_and_generic():
    assert b.is_prose(PASSAGE)
    assert not b.is_prose("# t\n## 1 Scope\n" + "The present document defines things. " * 20)
    assert not b.is_prose("# t\n## 6.3 X\n" + "| a | b | c | d |\n" * 40)
    assert not b.is_prose("# t\n## 6.3 X\n" + "Foo ::= SEQUENCE { a INTEGER, b INTEGER, c {x}, d {y} } " * 12)
    assert not b.is_prose("# t\n## 5 X\nshort")


def test_copy_detection_and_validation():
    body = b.body_of(PASSAGE)
    assert b.copies_passage("What is the average downlink UE throughput in the gNB?", body)
    ok = "How do operators see typical data speeds per user on slices?"
    assert b.valid_question(ok, body)
    assert not b.valid_question("How does the average downlink UE throughput in the gNB work?", body)
    assert not b.valid_question("what is this passage about", body)  # no '?', mentions passage
    assert not b.valid_question("Too short?", body)


def test_gold_includes_identical_body_chunks():
    a = {"source": "TS_28_552_Rel-18.md", "chunk": 1, "text": PASSAGE}
    dup = {"source": "TS_28_552_Rel-18.md", "chunk": 9, "text": PASSAGE}
    other = {"source": "TS_28_552_Rel-18.md", "chunk": 3, "text": PASSAGE + "different"}
    assert b.gold_ids(a, [a, dup, other]) == ["TS_28_552_Rel-18.md#1", "TS_28_552_Rel-18.md#9"]


def test_sampling_is_seeded_capped_and_skips_runbooks():
    ps = [{"source": f"TS_{s}_00_Rel-18.md", "chunk": i,
           "text": PASSAGE.replace("5.1.1.2", f"5.{i}")} for s in (28, 38) for i in range(30)]
    ps.append({"source": "01_runbook.md", "chunk": 0, "text": PASSAGE})
    s1 = b.sample_chunks(ps, 100, per_spec=4, seed=1)
    assert s1 == b.sample_chunks(ps, 100, per_spec=4, seed=1)
    assert len(s1) == 8 and all(p["source"].startswith("TS_") for p in s1)


def test_generate_rejects_copies_and_keeps_good(monkeypatch):
    ps = [{"source": "TS_28_552_Rel-18.md", "chunk": i, "text": PASSAGE} for i in range(6)]
    answers = iter(["How does the average downlink UE throughput in the gNB work?",  # copy
                    "How do I see typical per-user data speed for each slice?"] * 10)
    rows = b.generate(lambda *a, **k: next(answers), ps, n=2, per_spec=6)
    assert len(rows) >= 1 and all(r["question"].endswith("?") for r in rows)
    assert all("copy" not in r["question"] for r in rows)


def test_eval_scores_chunk_level_not_file_level():
    rows = [{"id": "s1", "question": "q", "split": "A.md", "gold": ["A.md#2"]}]

    def fake(q, k, mode, rerank):  # right file, wrong chunk -> must NOT count as a hit
        return [{"source": "A.md", "chunk": 7}, {"source": "A.md", "chunk": 8}]
    out = e.run(rows, 5, fake)
    m = next(x for x in out if x["kind"] == "metrics")
    assert m["hit_at_k"] == 0.0

    def right(q, k, mode, rerank):
        return [{"source": "A.md", "chunk": 7}, {"source": "A.md", "chunk": 2}]
    m = next(x for x in e.run(rows, 5, right) if x["kind"] == "metrics")
    assert m["hit_at_k"] == 1.0 and m["mrr"] == 0.5
