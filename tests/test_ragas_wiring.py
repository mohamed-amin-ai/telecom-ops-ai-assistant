"""Fast, no-network tests for run_ragas.py's pure logic. The actual ragas.evaluate() call
needs a real judge model and is verified separately (see README: "RAGAS" and the `live` CI
job) -- that's inherently not something a fast unit test can meaningfully check."""
import json

from evals.run_ragas import load_rows


def _write(tmp_path, rows):
    p = tmp_path / "golden.jsonl"
    with p.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return str(p)


def test_load_rows_filters_unanswerable(tmp_path):
    path = _write(tmp_path, [
        {"question": "a", "reference": "x", "answerable": True},
        {"question": "b", "reference": "y", "answerable": False},
        {"question": "c", "reference": "z", "answerable": True},
    ])
    rows = load_rows(path, limit=0)
    assert [r["question"] for r in rows] == ["a", "c"]


def test_load_rows_respects_limit_by_sampling_not_truncating(tmp_path):
    rows_in = [{"question": str(i), "reference": "x", "answerable": True} for i in range(10)]
    path = _write(tmp_path, rows_in)
    rows = load_rows(path, limit=3)
    assert len(rows) <= 4  # step-based sampling can land on 3 or 4 depending on rounding
    # a spread sample, not just the first 3 -- confirms it isn't naive rows[:limit]
    assert rows[-1]["question"] != "2"


def test_load_rows_limit_zero_returns_everything_answerable(tmp_path):
    path = _write(tmp_path, [{"question": "a", "reference": "x", "answerable": True}] * 5)
    assert len(load_rows(path, limit=0)) == 5


def test_named_embeddings_pass_ragas_usage_event_validation():
    """Regression: LangChain's FastEmbedEmbeddings keeps a model OBJECT in `.model`, and
    ragas builds a usage event from it that must be a string -- every answer-relevancy row
    failed in CI (nan_rows 6/6) until the retrieval embeddings were wrapped with a name."""
    import asyncio

    import pytest

    pytest.importorskip("ragas", reason="eval extras (requirements-eval.txt) not installed")
    from ragas.embeddings import LangchainEmbeddingsWrapper

    from evals.run_ragas import NamedEmbeddings

    class ObjectModelEmbeddings:
        model = object()

        def embed_documents(self, texts):
            return [[0.1] * 4 for _ in texts]

        def embed_query(self, text):
            return [0.1] * 4

        async def aembed_documents(self, texts):
            return self.embed_documents(texts)

        async def aembed_query(self, text):
            return self.embed_query(text)

    wrapped = LangchainEmbeddingsWrapper(NamedEmbeddings(ObjectModelEmbeddings(), "bge-small"))
    assert wrapped.embed_query("x") == [0.1] * 4
    assert wrapped.embed_documents(["a", "b"]) == [[0.1] * 4] * 2
    assert asyncio.run(wrapped.aembed_query("x")) == [0.1] * 4
