import json

from evals.aggregate_ragas import main, summarize
from evals.run_ragas import load_rows

HARD, STD = "evals/golden_hard.jsonl", "evals/golden_set.jsonl"


def _row(split, f, ar=0.5, cp=1.0, cr=1.0):
    return {"id": "x", "question": "q", "split": split, "judge": "j", "faithfulness": f,
            "answer_relevancy": ar, "llm_context_precision_with_reference": cp, "context_recall": cr}


def test_summarize_excludes_failures_and_counts_them():
    s = summarize([_row("hard", 1.0), _row("hard", 0.5), _row("hard", None)])
    f = s["faithfulness"]
    assert f["scored"] == 2 and f["failed"] == 1 and f["mean"] == 0.75
    assert f["lo"] <= 0.75 <= f["hi"]


def test_shards_are_disjoint_and_cover_everything():
    shards = [load_rows([STD, HARD], 24, f"{i}/4") for i in range(4)]
    questions = [r["question"] for sh in shards for r in sh]
    assert len(questions) == 24 and len(set(questions)) == 24
    assert {r["split"] for sh in shards for r in sh} == {"standard", "hard"}
    assert sorted(len(sh) for sh in shards) == [6, 6, 6, 6]
    for sh in shards:  # every shard sees both sets, 3 each, not one set per shard
        assert sorted(r["split"] for r in sh) == ["hard"] * 3 + ["standard"] * 3
    whole = {r["question"] for r in load_rows([STD, HARD], 24, "0/1")}
    assert whole == set(questions)  # the shards together are exactly the unsharded sample


def test_sample_is_a_balanced_mix_and_deterministic():
    rows = load_rows([STD, HARD], 24)
    assert sum(r["split"] == "hard" for r in rows) == 12 and sum(r["split"] == "standard" for r in rows) == 12
    assert rows == load_rows([STD, HARD], 24)


def test_cli_pools_shards_and_fails_when_a_metric_never_parses(tmp_path, monkeypatch, capsys):
    good = [_row("standard", 0.9), _row("hard", 0.7)]
    broken = [_row("hard", 0.8, ar=None), _row("hard", 0.6, ar=None)]
    (tmp_path / "a.json").write_text(json.dumps(good))
    (tmp_path / "b.json").write_text(json.dumps(broken))
    files = [str(tmp_path / "a.json"), str(tmp_path / "b.json")]
    monkeypatch.setattr("sys.argv", ["x", *files])
    assert main() == 0  # answer_relevancy scored 2/4: exactly at the default 0.5 floor
    monkeypatch.setattr("sys.argv", ["x", *files, "--min-scored", "0.6"])
    assert main() == 1  # but not enough for a stricter floor
    assert "answer_relevancy: only 2/4 rows scored" in capsys.readouterr().out
    # a metric that never parses on any row must always fail, whatever the floor
    never = [_row("hard", 0.8, ar=None), _row("hard", 0.6, ar=None)]
    (tmp_path / "c.json").write_text(json.dumps(never))
    monkeypatch.setattr("sys.argv", ["x", str(tmp_path / "c.json"), "--min-scored", "0.0"])
    assert main() == 1
