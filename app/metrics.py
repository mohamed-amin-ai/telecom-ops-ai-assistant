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


def render() -> tuple[bytes, str]:
    if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
