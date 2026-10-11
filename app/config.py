import os
from dataclasses import dataclass


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(int(default))).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    llm_model: str = os.getenv("LLM_MODEL", "ollama_chat/qwen2.5:3b-instruct")
    llm_fallback_model: str = os.getenv("LLM_FALLBACK_MODEL", "ollama_chat/qwen2.5:3b-instruct")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
    # Self-hosted vLLM (OpenAI-compatible server). Use model strings "hosted_vllm/<served-model>"
    # for LLM_MODEL / LLM_FALLBACK_MODEL / JUDGE_MODEL / GUARD_MODEL.
    vllm_base_url: str = os.getenv("VLLM_BASE_URL", "http://vllm:8000/v1")
    vllm_api_key: str = os.getenv("VLLM_API_KEY", "")

    # "agentic": the model chooses among read-only tools (bounded); "fixed": always KPI profile
    # + runbook search. Writes (tickets) are never model-callable in either mode.
    agent_mode: str = os.getenv("AGENT_MODE", "agentic")
    agent_max_steps: int = int(os.getenv("AGENT_MAX_STEPS", "5"))  # tool calls per incident
    tools_via_mcp: bool = _flag("TOOLS_VIA_MCP", True)  # agent reads go through app/mcp_server.py

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
    db_pool_max: int = int(os.getenv("DB_POOL_MAX", "10"))
    judge_model: str = os.getenv("JUDGE_MODEL", "ollama_chat/qwen2.5:3b-instruct")

    guardrails_enabled: bool = _flag("GUARDRAILS", True)
    guard_llm: bool = _flag("GUARD_LLM", True)
    guard_model: str = os.getenv("GUARD_MODEL", "ollama_chat/qwen2.5:3b-instruct")

    # Auth and limits. AUTH_REQUIRED=0 is for local hacking only: every caller becomes admin.
    auth_required: bool = _flag("AUTH_REQUIRED", True)
    rate_limit_per_min: int = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))  # per user
    ip_rate_limit_per_min: int = int(os.getenv("IP_RATE_LIMIT_PER_MIN", "120"))  # per client IP
    # Number of reverse proxies in front of the API that append to X-Forwarded-For. 0 means
    # trust nothing: use the socket peer address (correct when the API is exposed directly).
    trusted_proxies: int = int(os.getenv("TRUSTED_PROXIES", "0"))
    cors_origins: str = os.getenv("CORS_ORIGINS", "")  # comma-separated; empty = no CORS
    root_path: str = os.getenv("ROOT_PATH", "")  # e.g. /api when served under a path prefix
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # Optional SSO: accept "Authorization: Bearer <JWT>" from an OIDC provider (Keycloak, Okta,
    # Entra, ...) in addition to API keys. Set OIDC_ISSUER and OIDC_AUDIENCE, plus either
    # OIDC_JWKS_URL (fetched and cached) or OIDC_JWKS_JSON (static, for air-gapped or tests).
    oidc_issuer: str = os.getenv("OIDC_ISSUER", "")
    oidc_audience: str = os.getenv("OIDC_AUDIENCE", "")
    oidc_jwks_url: str = os.getenv("OIDC_JWKS_URL", "")
    oidc_jwks_json: str = os.getenv("OIDC_JWKS_JSON", "")
    oidc_role_claim: str = os.getenv("OIDC_ROLE_CLAIM", "roles")  # or "groups"; dotted for nested
    oidc_name_claim: str = os.getenv("OIDC_NAME_CLAIM", "preferred_username")

    log_json: bool = _flag("LOG_JSON", True)
    sentry_dsn: str = os.getenv("SENTRY_DSN", "")
    sentry_traces_sample_rate: float = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0"))

    # Optional ITSM hand-off: POST every approved ticket here (HMAC-signed if a secret is set).
    ticket_webhook_url: str = os.getenv("TICKET_WEBHOOK_URL", "")
    ticket_webhook_secret: str = os.getenv("TICKET_WEBHOOK_SECRET", "")
    # "generic" posts the ticket as-is; "jira" posts a Jira REST (v2) issue-create body.
    ticket_webhook_format: str = os.getenv("TICKET_WEBHOOK_FORMAT", "generic")
    ticket_webhook_auth: str = os.getenv("TICKET_WEBHOOK_AUTH", "")  # full Authorization header
    jira_project_key: str = os.getenv("JIRA_PROJECT_KEY", "NOC")
    jira_issue_type: str = os.getenv("JIRA_ISSUE_TYPE", "Incident")


settings = Settings()
