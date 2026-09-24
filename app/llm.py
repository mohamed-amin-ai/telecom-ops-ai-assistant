import os

import litellm

from .config import settings

if os.getenv("LANGFUSE_PUBLIC_KEY"):
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]


def chat(messages: list[dict], model: str | None = None, **kw) -> str:
    """Single LLM entry point. Primary = hosted (Anthropic); falls back to local Ollama."""
    model = model or settings.llm_model
    kw.setdefault("temperature", 0)
    try:
        r = litellm.completion(model=model, messages=messages, **kw)
    except Exception:
        if model == settings.llm_fallback_model:
            raise
        r = litellm.completion(
            model=settings.llm_fallback_model,
            messages=messages,
            api_base=settings.ollama_base_url,
            **kw,
        )
    return r.choices[0].message.content
