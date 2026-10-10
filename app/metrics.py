"""Prometheus metrics. Works with multiple uvicorn workers when PROMETHEUS_MULTIPROC_DIR is
set (the prod compose does): each worker writes to that dir and /metrics aggregates them."""
import os

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
LLM_CALLS = Counter("llm_calls_total", "LLM calls", ["model", "outcome"])
LLM_LATENCY = Histogram(
    "llm_call_duration_seconds", "LLM call latency", ["model"],
    buckets=(0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
GUARD_BLOCKS = Counter("guardrail_blocks_total", "Requests blocked by guardrails", ["label"])
RATE_LIMITED = Counter("ratelimit_rejections_total", "Requests rejected by rate limits", ["scope"])
AUTH_FAILURES = Counter("auth_failures_total", "Authentication/authorization failures", ["reason"])
APPROVALS = Counter("approvals_total", "Incident decisions", ["decision"])
TICKETS = Counter("tickets_created_total", "Tickets created")

# Quality signals for the running system (not just "is it up"):
ANSWERS = Counter(
    "answers_total",
    "Answers to /ask by outcome: cited (has a runbook citation), abstained (said the docs "
    "don't cover it), unverified (neither -- may be hallucinated), blocked (guardrail)",
    ["outcome"],
)
RETRIEVAL_EMPTY = Counter("retrieval_empty_total", "Retrievals that returned no passages")
APPROVAL_WAIT = Histogram(
    "approval_wait_seconds", "Time from incident opened to an approve/reject decision",
    buckets=(30, 60, 300, 900, 1800, 3600, 7200, 21600, 86400),
)
WEBHOOK = Counter("ticket_webhook_total", "ITSM webhook deliveries by outcome", ["status"])


def kpi_freshness_lines() -> bytes:
    """Gauges computed at scrape time (a value that must be fresh at scrape, not left over
    from whichever worker last wrote it). kpi_data_age_seconds is how old the newest KPI
    reading is: if the data feed dies the assistant keeps answering from stale numbers and
    nothing else notices. db_up is 0 when the lookup itself fails."""
    from .db import get_pool

    try:
        with get_pool().connection() as conn:
            age = conn.execute(
                "SELECT EXTRACT(EPOCH FROM (now() - max(ts))) FROM kpis").fetchone()[0]
        lines = ["# TYPE db_up gauge", "db_up 1"]
        if age is not None:
            lines += ["# TYPE kpi_data_age_seconds gauge", f"kpi_data_age_seconds {float(age):.1f}"]
    except Exception:  # noqa: BLE001 -- a metrics scrape must never fail because the DB did
        lines = ["# TYPE db_up gauge", "db_up 0"]
    return ("\n".join(lines) + "\n").encode()


def render() -> tuple[bytes, str]:
    if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
