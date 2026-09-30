import logging
import os
import time

import litellm

from . import metrics
from .config import settings

log = logging.getLogger("llm")

MOCK = os.getenv("LLM_MOCK") == "1"
MOCK_TEXT = "Mock LLM response (LLM_MOCK=1). See [mock.md#0]."

if os.getenv("LANGFUSE_PUBLIC_KEY"):
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]


def _timed(model: str, messages: list[dict], kw: dict):
    t0 = time.perf_counter()
    try:
        r = _complete(model, messages, kw)
    except Exception:
        metrics.LLM_CALLS.labels(model, "error").inc()
        raise
    finally:
        metrics.LLM_LATENCY.labels(model).observe(time.perf_counter() - t0)
    metrics.LLM_CALLS.labels(model, "ok").inc()
    return r


def _complete(model: str, messages: list[dict], kw: dict):
    """Call litellm, dropping an unsupported `temperature` and retrying once.
    Some Claude models (e.g. claude-sonnet-5) only accept temperature=1 and raise
    litellm.UnsupportedParamsError for our default of 0."""
    kw.setdefault("num_retries", 3)  # litellm backs off on RateLimitError/5xx/timeouts
    try:
        return litellm.completion(model=model, messages=messages, **kw)
    except litellm.exceptions.UnsupportedParamsError as e:
        if "temperature" in kw and "temperature" in str(e).lower():
            kw = {k: v for k, v in kw.items() if k != "temperature"}
            return litellm.completion(model=model, messages=messages, **kw)
        raise


def chat(messages: list[dict], model: str | None = None, **kw) -> str:
    """Single LLM entry point. Primary = hosted (Anthropic/OpenRouter); falls back to
    local Ollama."""
    if MOCK:
        return MOCK_TEXT
    model = model or settings.llm_model
    kw.setdefault("temperature", 0)
    # A reasonable ceiling, not "however much the model allows": some providers (found via
    # OpenRouter) preflight-check cost against max_tokens before the call even runs, and
    # reject it if the account can't cover the model's full window even though actual usage
    # would be far smaller. Our answers are prose paragraphs, not long documents.
    kw.setdefault("max_tokens", 1024)
    try:
        r = _timed(model, messages, kw)
    except Exception as primary_err:
        if model == settings.llm_fallback_model:
            raise
        log.warning("primary LLM call failed (model=%s), falling back to %s: %s",
                    model, settings.llm_fallback_model, primary_err)
        try:
            r = _timed(settings.llm_fallback_model, messages,
                       {**kw, "api_base": settings.ollama_base_url})
        except Exception as fallback_err:
            # Re-raise the PRIMARY error: it's almost always the one that actually
            # needs fixing (bad model string, missing key, provider outage). The
            # fallback failing too (e.g. no local Ollama running) is expected in most
            # deployments and would otherwise mask the real problem.
            raise primary_err from fallback_err
    return r.choices[0].message.content
