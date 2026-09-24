from app.rag import ingest

if __name__ == "__main__":
    print(f"ingested {ingest(recreate=True)} chunks")
