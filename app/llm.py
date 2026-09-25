import os

import litellm

from .config import settings

MOCK = os.getenv("LLM_MOCK") == "1"
MOCK_TEXT = "Mock LLM response (LLM_MOCK=1). See [mock.md#0]."

if os.getenv("LANGFUSE_PUBLIC_KEY"):
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]


def _complete(model: str, messages: list[dict], kw: dict):
    """Call litellm, dropping an unsupported `temperature` and retrying once.
    Some Claude models (e.g. claude-sonnet-5) only accept temperature=1 and raise
    litellm.UnsupportedParamsError for our default of 0."""
    try:
        return litellm.completion(model=model, messages=messages, **kw)
    except litellm.exceptions.UnsupportedParamsError as e:
        if "temperature" in kw and "temperature" in str(e).lower():
            kw = {k: v for k, v in kw.items() if k != "temperature"}
            return litellm.completion(model=model, messages=messages, **kw)
        raise


def chat(messages: list[dict], model: str | None = None, **kw) -> str:
    """Single LLM entry point. Primary = hosted (Anthropic); falls back to local Ollama."""
    if MOCK:
        return MOCK_TEXT
    model = model or settings.llm_model
    kw.setdefault("temperature", 0)
    try:
        r = _complete(model, messages, kw)
    except Exception:
        if model == settings.llm_fallback_model:
            raise
        r = _complete(settings.llm_fallback_model, messages,
                      {**kw, "api_base": settings.ollama_base_url})
    return r.choices[0].message.content
