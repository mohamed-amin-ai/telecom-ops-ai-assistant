"""Sanity-check an ingested 3GPP corpus: every converted spec has chunks in Qdrant and a few
telecom queries surface text containing the expected term. These are smoke checks that the
conversion/ingest pipeline produced searchable content, NOT a retrieval-quality measurement
(that needs questions with known answers from these specs, which don't exist yet)."""
import json
import sys
from pathlib import Path

from qdrant_client import models

from app.config import settings
from app.rag import _client, retrieve

CHECKS = [
    ("E-RAB setup success rate definition", "E-RAB"),
    ("downlink PRB usage measurement", "PRB"),
    ("handover execution success rate", "handover"),
    # Identifier query: lexical (BM25) matching of protocol identifiers is what ops lookups need.
    ("RRCReconfiguration reconfigurationWithSync handover", "reconfigurationWithSync"),
    ("5G registration procedure AMF", "AMF"),
]


# Plain-English queries whose answer text uses protocol identifiers. Reported, NOT gating:
# a miss here is a real retrieval limitation worth knowing about, not a broken pipeline.
INFO_CHECKS = [
    ("RRC reconfiguration with synchronisation for handover", "reconfigurationWithSync"),
]


def main(manifest_path: str = "data/3gpp/MANIFEST.json", min_chunks: int = 20) -> int:
    manifest = json.loads(Path(manifest_path).read_text())
    ok_specs = [s for s in manifest["specs"] if s["status"] == "ok"]
    fail = 0
    for s in manifest["specs"]:
        if s["status"] != "ok":  # a requested spec that did not convert is a failure, not a skip
            print(f"FAIL  {s['spec']}: {s['status']}")
            fail += 1
    if not ok_specs:
        print("FAIL no specs converted")
        return 1
    for s in ok_specs:
        n = _client().count(settings.collection, count_filter=models.Filter(must=[
            models.FieldCondition(key="source", match=models.MatchValue(value=s["file"]))]),
            exact=True).count
        flag = "PASS" if n >= min_chunks else "FAIL"
        fail += flag == "FAIL"
        print(f"{flag}  {s['spec']} v{s['version']}: {n} chunks")
    for q, term in CHECKS:
        hits = retrieve(q, k=5)
        found = any(term.lower() in h["text"].lower() for h in hits)
        srcs = ", ".join(sorted({h["source"] for h in hits}))
        print(f"{'PASS' if found else 'FAIL'}  '{q}' -> contains '{term}' in top-5 [{srcs}]")
        fail += not found
    for q, term in INFO_CHECKS:
        hits = retrieve(q, k=5)
        found = any(term.lower() in h["text"].lower() for h in hits)
        print(f"INFO  {'found' if found else 'MISSED'}  '{q}' -> '{term}' in top-5 "
              f"[{', '.join(sorted({h['source'] for h in hits}))}]")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
