"""RAGAS evaluation: faithfulness, answer relevancy, context precision, context recall.

Needs a real, reasonably capable judge model -- run this in a live-model context
(the `live` CI job, or locally against a real ANTHROPIC_API_KEY/OPENROUTER_API_KEY), not
against the fake Anthropic server (it would just be scoring the fake server's canned text)
or the free Ollama model (too small to be a reliable judge; RAGAS's prompts expect
consistent structured JSON back).

  python -m evals.run_ragas [path] [--limit 20] [--min-faithfulness 0.7] ...

Only answerable questions are used (RAGAS's metrics assume there is a correct answer to
compare against; scoring abstentions is what evals/run_gen_eval.py already does).
"""
import argparse
import json
import math
import sys
import warnings

from app.config import settings
from app.rag import answer


def load_rows(path: str, limit: int) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    rows = [r for r in rows if r.get("answerable")]
    if limit:
        step = max(1, len(rows) // limit)
        rows = rows[::step][:limit]
    return rows


def build_dataset(rows: list[dict]):
    from ragas.dataset_schema import EvaluationDataset, SingleTurnSample

    samples = []
    for r in rows:
        out = answer(r["question"])
        samples.append(SingleTurnSample(
            user_input=r["question"],
            response=out["answer"],
            retrieved_contexts=out["contexts"] or [""],
            reference=r["reference"],
        ))
    return EvaluationDataset(samples=samples)


class NamedEmbeddings:
    """Adapter exposing the retrieval embeddings with `model` as the model NAME.

    ragas's LangChain wrapper builds a usage event from getattr(embeddings, "model"), which
    must be a string. LangChain's FastEmbedEmbeddings keeps the loaded model OBJECT in
    `.model`, so every answer-relevancy row failed validation (nan_rows 6/6 in CI)."""

    def __init__(self, inner, name: str):
        self._inner, self.model = inner, name

    def embed_documents(self, texts):
        return self._inner.embed_documents(texts)

    def embed_query(self, text):
        return self._inner.embed_query(text)

    async def aembed_documents(self, texts):
        return await self._inner.aembed_documents(texts)

    async def aembed_query(self, text):
        return await self._inner.aembed_query(text)


def build_llm_and_embeddings(request_timeout: int = 120):
    """Real judge model (the app's own LLM_MODEL) and real embeddings (the app's own
    retrieval embeddings), wrapped for RAGAS. Kept as a function so a test can monkeypatch
    it without needing a live model or a network-fetched embedding model."""
    # LangchainLLMWrapper/LangchainEmbeddingsWrapper are the deprecated-but-stable path as
    # of ragas 0.4.x; ragas's newer instructor-based ragas.metrics.collections API needs a
    # different LLM wrapper stack (the `instructor` library) not otherwise used in this repo.
    # Revisit when ragas 1.0 removes this path.
    import litellm
    from langchain_community.embeddings import FastEmbedEmbeddings
    from langchain_litellm import ChatLiteLLM
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    # ResponseRelevancy requests several completions per call (n=strictness); Ollama doesn't
    # support `n`, and litellm raises instead of ignoring it. Dropping unsupported params
    # here (this script only, not the app) means such a provider returns one completion
    # and RAGAS scores from that, instead of every relevancy row failing.
    litellm.drop_params = True
    # No explicit temperature: some models (claude-sonnet-5) reject temperature=0, and
    # app/llm.py's retry-without-temperature workaround doesn't apply to this bare
    # LangChain wrapper, so it's simplest to just let the provider use its own default.
    chat = ChatLiteLLM(model=settings.llm_model, max_tokens=1024, max_retries=3,
                       request_timeout=request_timeout)
    llm = LangchainLLMWrapper(chat)
    embeddings = LangchainEmbeddingsWrapper(
        NamedEmbeddings(FastEmbedEmbeddings(model_name=settings.dense_model), settings.dense_model))
    return llm, embeddings


def run(path: str, limit: int, workers: int = 16, timeout: int = 180) -> dict:
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="ragas")
    from ragas import evaluate
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )
    from ragas.run_config import RunConfig

    rows = load_rows(path, limit)
    if not rows:
        raise SystemExit(f"no answerable rows found in {path}")
    dataset = build_dataset(rows)
    # A CPU-bound local judge answers one request at a time, so ragas's defaults (16
    # parallel workers, 180s per call) just make calls queue and time out. Callers running a
    # slow judge pass workers=1-2 and a generous timeout.
    llm, embeddings = build_llm_and_embeddings(request_timeout=timeout)
    metrics = [
        Faithfulness(llm=llm),
        ResponseRelevancy(llm=llm, embeddings=embeddings, strictness=1),
        LLMContextPrecisionWithReference(llm=llm),
        LLMContextRecall(llm=llm),
    ]
    result = evaluate(dataset, metrics=metrics, show_progress=False, raise_exceptions=False,
                      run_config=RunConfig(timeout=timeout, max_workers=workers, max_retries=3))
    df = result.to_pandas()
    metric_cols = ["faithfulness", "answer_relevancy",
                   "llm_context_precision_with_reference", "context_recall"]
    present = [c for c in metric_cols if c in df.columns]
    nan_counts = {c: int(df[c].isna().sum()) for c in present}
    scores = df[present].mean(numeric_only=True).to_dict()
    return {"n": len(rows), "nan_rows": nan_counts,
            **{k: (None if math.isnan(v) else round(float(v), 3)) for k, v in scores.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="evals/golden_set.jsonl")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--min-faithfulness", type=float, default=0.0)
    ap.add_argument("--min-answer-relevancy", type=float, default=0.0)
    ap.add_argument("--min-context-precision", type=float, default=0.0)
    ap.add_argument("--min-context-recall", type=float, default=0.0)
    a = ap.parse_args()

    result = run(a.path, a.limit, a.workers, a.timeout)
    result["judge"] = settings.llm_model
    print(json.dumps(result))

    floors = {
        "faithfulness": a.min_faithfulness,
        "answer_relevancy": a.min_answer_relevancy,
        "llm_context_precision_with_reference": a.min_context_precision,
        "context_recall": a.min_context_recall,
    }
    failed = [
        f"{k}={result.get(k)} < {v}" if result.get(k) is not None else f"{k}=NaN (parse failures, see nan_rows)"
        for k, v in floors.items()
        if v > 0 and (result.get(k) is None or result.get(k) < v)
    ]
    if failed:
        print("BELOW FLOOR:", *failed, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
