import os
from dataclasses import dataclass


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(int(default))).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    llm_model: str = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-5")
    llm_fallback_model: str = os.getenv("LLM_FALLBACK_MODEL", "ollama/qwen2.5:7b-instruct")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

    qdrant_url: str = os.getenv("QDRANT_URL", "http://qdrant:6333")
    collection: str = os.getenv("QDRANT_COLLECTION", "telecom_docs")
    dense_model: str = os.getenv("DENSE_MODEL", "BAAI/bge-small-en-v1.5")
    sparse_model: str = os.getenv("SPARSE_MODEL", "Qdrant/bm25")
    rerank_model: str = os.getenv("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
    retrieval_mode: str = os.getenv("RETRIEVAL_MODE", "hybrid")  # dense | hybrid
    rerank: bool = _flag("RERANK", False)
    top_k: int = int(os.getenv("TOP_K", "5"))

    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://telecom:telecom@localhost:5432/telecom"
    )
    judge_model: str = os.getenv("JUDGE_MODEL", "anthropic/claude-haiku-4-5-20251001")

    guardrails_enabled: bool = _flag("GUARDRAILS", True)
    guard_llm: bool = _flag("GUARD_LLM", True)
    guard_model: str = os.getenv("GUARD_MODEL", "anthropic/claude-haiku-4-5-20251001")
    rate_limit_per_min: int = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))
    api_key: str = os.getenv("API_KEY", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")


settings = Settings()
