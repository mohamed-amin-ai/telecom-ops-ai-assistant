import json
from pathlib import Path

from app.guardrails import CLASSIFIER_EXAMPLES

EVALS = Path(__file__).resolve().parent.parent / "evals"


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def test_few_shot_examples_are_not_copied_from_the_eval_sets():
    evaluated = set()
    for name in ("redteam_set.jsonl", "guardrail_set.jsonl"):
        for line in (EVALS / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                evaluated.add(_norm(json.loads(line)["text"]))
    leaked = [q for q, _ in CLASSIFIER_EXAMPLES if _norm(q) in evaluated]
    assert not leaked, f"few-shot examples duplicate eval cases (contaminates the eval): {leaked}"


def test_examples_cover_every_label_and_are_valid():
    labels = {lab for _, lab in CLASSIFIER_EXAMPLES}
    assert labels == {"on_topic", "off_topic", "injection", "harmful"}
    assert sum(lab == "on_topic" for _, lab in CLASSIFIER_EXAMPLES) >= 5  # the failure was FPs
