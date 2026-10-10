from unittest.mock import patch

import litellm
import pytest

from app.llm import _complete


class _Choice:
    def __init__(self, text):
        self.message = type("M", (), {"content": text})


class _Resp:
    def __init__(self, text):
        self.choices = [_Choice(text)]


def test_drops_temperature_on_unsupported_params_error():
    """Regression: litellm rejects temperature=0 for some model strings
    (e.g. strict-temp-model, which only accepts temperature=1)."""
    calls = []

    def fake_completion(model, messages, **kw):
        calls.append(dict(kw))
        if "temperature" in kw:
            raise litellm.exceptions.UnsupportedParamsError(
                message="strict-temp-model does not support temperature=0. "
                        "Only temperature=1 is supported.",
                status_code=400,
            )
        return _Resp("ok")

    with patch("app.llm.litellm.completion", side_effect=fake_completion):
        r = _complete("anthropic/strict-temp-model", [{"role": "user", "content": "hi"}],
                      {"temperature": 0})
    assert r.choices[0].message.content == "ok"
    assert len(calls) == 2
    assert "temperature" in calls[0] and "temperature" not in calls[1]


def test_unrelated_unsupported_param_error_is_not_swallowed():
    def fake_completion(model, messages, **kw):
        raise litellm.exceptions.UnsupportedParamsError(message="bad `top_k`", status_code=400)

    with patch("app.llm.litellm.completion", side_effect=fake_completion), pytest.raises(
        litellm.exceptions.UnsupportedParamsError
    ):
        _complete("anthropic/strict-temp-model", [{"role": "user", "content": "hi"}], {"top_k": 1})


def test_no_retry_when_temperature_not_set():
    def fake_completion(model, messages, **kw):
        raise litellm.exceptions.UnsupportedParamsError(message="temperature issue", status_code=400)

    with patch("app.llm.litellm.completion", side_effect=fake_completion), pytest.raises(
        litellm.exceptions.UnsupportedParamsError
    ):
        _complete("anthropic/strict-temp-model", [{"role": "user", "content": "hi"}], {})


def test_chat_raises_primary_error_when_fallback_also_fails():
    """Regression: a swallowed primary-provider error made a real failure (bad model
    string, missing key, provider outage) indistinguishable from 'no local Ollama
    running', which is expected in most deployments and not the real problem."""
    from app import llm

    def fake_completion(model, messages, **kw):
        if "strict-temp" in model:
            raise ValueError("primary: invalid model string")
        raise ValueError("fallback: connection refused")

    with patch("app.llm.litellm.completion", side_effect=fake_completion), pytest.raises(
        ValueError, match="primary: invalid model string"
    ):
        llm.chat([{"role": "user", "content": "hi"}], model="gateway/x/strict-temp-model")


def test_complete_defaults_num_retries_for_transient_errors():
    """Hosted providers rate-limit in short bursts; litellm's own
    num_retries handles backoff for RateLimitError/5xx/timeouts. Regression: found via a
    live CI run hitting a new-account rate cap with no retry at all."""
    from app.llm import _complete

    seen = {}

    def fake_completion(model, messages, **kw):
        seen.update(kw)
        return _Resp("ok")

    with patch("app.llm.litellm.completion", side_effect=fake_completion):
        _complete("anthropic/strict-temp-model", [{"role": "user", "content": "hi"}], {})
    assert seen.get("num_retries") == 3


def test_complete_respects_explicit_num_retries():
    from app.llm import _complete

    seen = {}

    def fake_completion(model, messages, **kw):
        seen.update(kw)
        return _Resp("ok")

    with patch("app.llm.litellm.completion", side_effect=fake_completion):
        _complete("anthropic/strict-temp-model", [{"role": "user", "content": "hi"}],
                  {"num_retries": 5})
    assert seen.get("num_retries") == 5


def test_chat_defaults_a_reasonable_max_tokens():
    """Regression: found via a live CI run against a hosted gateway, which preflight-checks
    cost against max_tokens and rejects the call if the account can't cover the model's
    full window (65536 for strict-temp-model) even when actual usage would be tiny."""
    from app import llm

    seen = {}

    def fake_completion(model, messages, **kw):
        seen.update(kw)
        return _Resp("ok")

    with patch("app.llm.litellm.completion", side_effect=fake_completion):
        llm.chat([{"role": "user", "content": "hi"}])
    assert seen.get("max_tokens") == 1024


def test_chat_respects_explicit_max_tokens():
    from app import llm

    seen = {}

    def fake_completion(model, messages, **kw):
        seen.update(kw)
        return _Resp("ok")

    with patch("app.llm.litellm.completion", side_effect=fake_completion):
        llm.chat([{"role": "user", "content": "hi"}], max_tokens=30)
    assert seen.get("max_tokens") == 30


def test_broken_tracing_callback_does_not_break_answering(monkeypatch):
    calls = {"n": 0}

    def fake(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ImportError("langfuse>=4.7 required")
        return _Resp("ok")

    monkeypatch.setattr(litellm, "success_callback", ["langfuse"])
    monkeypatch.setattr(litellm, "failure_callback", ["langfuse"])
    with patch("litellm.completion", side_effect=fake):
        r = _complete("m", [{"role": "user", "content": "x"}], {})
    assert r.choices[0].message.content == "ok"
    assert litellm.success_callback == [] and litellm.failure_callback == []


def test_import_error_without_tracing_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(litellm, "success_callback", [])
    monkeypatch.setattr(litellm, "failure_callback", [])
    with patch("litellm.completion", side_effect=ImportError("boom")), pytest.raises(ImportError):
        _complete("m", [{"role": "user", "content": "x"}], {})


def test_route_sends_vllm_models_to_vllm(monkeypatch):
    from app import llm
    monkeypatch.setattr(llm.settings.__class__, "vllm_base_url", "http://v:8000/v1", raising=False)
    r = llm.route("hosted_vllm/Qwen/Qwen2.5-7B-Instruct")
    assert r["api_base"] == llm.settings.vllm_base_url
    assert r["api_key"]  # never empty: the OpenAI SDK refuses an empty key
    assert llm.route("anthropic/strict-temp-model") == {}
    assert llm.route("ollama/qwen2.5:7b-instruct") == {}


def test_chat_passes_vllm_base_url_and_key():
    from app import llm
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return _Resp("hi")

    with patch("litellm.completion", side_effect=fake):
        out = llm.chat([{"role": "user", "content": "x"}], model="hosted_vllm/m")
    assert out == "hi"
    assert seen["api_base"] == llm.settings.vllm_base_url and seen["api_key"]


def test_fallback_to_ollama_does_not_inherit_vllm_connection(monkeypatch):
    from app import llm
    monkeypatch.setattr(llm, "MOCK", False)
    calls = []

    def fake(**kw):
        calls.append(kw)
        if kw["model"].startswith("hosted_vllm/"):
            raise RuntimeError("vllm down")
        return _Resp("fallback")

    with patch("litellm.completion", side_effect=fake):
        out = llm.chat([{"role": "user", "content": "x"}], model="hosted_vllm/m")
    assert out == "fallback"
    assert calls[-1]["api_base"] == llm.settings.ollama_base_url
    assert "api_key" not in calls[-1]
