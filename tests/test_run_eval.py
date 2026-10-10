from evals.run_eval import CONFIGS, compare, run, summarize

STD = "evals/golden_set.jsonl"
HARD = "evals/golden_hard.jsonl"


def _fake_retrieve(perfect_modes):
    """A retriever that is perfect for the given (mode, rerank) configs and misses entirely
    for the others -- so every expected number below is derivable by hand."""
    from evals.run_eval import load

    rows = {r["question"]: r for s, p in ((("standard", STD), ("hard", HARD))) for r in load(p, s)}

    def retrieve(q, k=3, mode="hybrid", rerank=False):
        if (mode, rerank) in perfect_modes:
            return [{"source": s} for s in rows[q]["expected_sources"]]
        return [{"source": "nope.md"}]
    return retrieve


def test_sets_load_and_are_distinct():
    from evals.run_eval import load

    std, hard = load(STD, "standard"), load(HARD, "hard")
    assert len(std) == 110 and len(hard) == 38
    assert not {r["question"] for r in std} & {r["question"] for r in hard}


def test_perfect_vs_broken_retriever_gives_exact_numbers_and_significance():
    lines, _ = run(3, _fake_retrieve({("hybrid", False), ("hybrid", True)}))
    m = {(x["split"], x["mode"], x["rerank"]): x for x in lines if x["kind"] == "metrics"}
    dense = m[("all", "dense", False)]
    hybrid = m[("all", "hybrid", False)]
    assert dense["hit_at_k"] == 0.0 and dense["mrr"] == 0.0 and dense["ndcg"] == 0.0
    assert hybrid["hit_at_k"] == 1.0 and hybrid["mrr"] == 1.0 and hybrid["ndcg"] == 1.0
    assert hybrid["n"] == 148
    assert hybrid["hit_lo"] > 0.97 and dense["hit_hi"] < 0.03  # Wilson at 100% and 0%
    cmp_ = next(x for x in lines if x["kind"] == "compare" and x["split"] == "all"
                and x["a"] == "dense" and x["b"] == "hybrid")
    assert cmp_["rr_mean_diff"] == 1.0 and cmp_["rr_significant"]
    assert cmp_["hit_only_b"] == 148 and cmp_["hit_only_a"] == 0 and cmp_["hit_mcnemar_p"] < 1e-6
    same = next(x for x in lines if x["kind"] == "compare" and x["split"] == "all"
                and x["a"] == "hybrid" and x["b"] == "hybrid+rerank")
    assert same["rr_mean_diff"] == 0.0 and not same["rr_significant"] and same["hit_mcnemar_p"] == 1.0


def test_every_config_and_split_is_reported():
    lines, _ = run(3, _fake_retrieve(set(CONFIGS)))
    keys = {(x["split"], x["mode"], x["rerank"]) for x in lines if x["kind"] == "metrics"}
    assert keys == {(s, mo, r) for s in ("all", "standard", "hard") for mo, r in CONFIGS}


def test_summarize_and_compare_handle_a_partial_miss():
    a = [{"hit": 1.0, "rr": 1.0, "ndcg": 1.0, "recall": 1.0, "split": "s"} for _ in range(8)]
    b = a[:6] + [{"hit": 0.0, "rr": 0.0, "ndcg": 0.0, "recall": 0.0, "split": "s"}] * 2
    s = summarize(b, 3)
    assert s["hit_at_k"] == 0.75 and s["hit_lo"] < 0.75 < s["hit_hi"]
    c = compare(a, b)
    assert c["hit_only_a"] == 2 and c["hit_only_b"] == 0 and c["hit_mcnemar_p"] == 0.5
