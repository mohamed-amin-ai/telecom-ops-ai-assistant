import argparse

from app.rag import ingest

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", nargs="+", default=["data/docs"],
                    help="one or more directories (e.g. data/docs data/3gpp)")
    a = ap.parse_args()
    print(f"ingested {ingest(a.docs, recreate=True)} chunks from {', '.join(a.docs)}")
