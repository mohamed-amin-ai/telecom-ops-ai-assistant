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
    """Regression: litellm rejects temperature=0 for some Claude model strings
    (e.g. claude-sonnet-5, which only accepts temperature=1)."""
    calls = []

    def fake_completion(model, messages, **kw):
        calls.append(dict(kw))
        if "temperature" in kw:
            raise litellm.exceptions.UnsupportedParamsError(
                message="claude-sonnet-5 does not support temperature=0. "
                        "Only temperature=1 is supported.",
                status_code=400,
            )
        return _Resp("ok")

    with patch("app.llm.litellm.completion", side_effect=fake_completion):
        r = _complete("anthropic/claude-sonnet-5", [{"role": "user", "content": "hi"}],
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
        _complete("anthropic/claude-sonnet-5", [{"role": "user", "content": "hi"}], {"top_k": 1})


def test_no_retry_when_temperature_not_set():
    def fake_completion(model, messages, **kw):
        raise litellm.exceptions.UnsupportedParamsError(message="temperature issue", status_code=400)

    with patch("app.llm.litellm.completion", side_effect=fake_completion), pytest.raises(
        litellm.exceptions.UnsupportedParamsError
    ):
        _complete("anthropic/claude-sonnet-5", [{"role": "user", "content": "hi"}], {})


def test_chat_raises_primary_error_when_fallback_also_fails():
    """Regression: a swallowed primary-provider error made a real failure (bad model
    string, missing key, provider outage) indistinguishable from 'no local Ollama
    running', which is expected in most deployments and not the real problem."""
    from app import llm

    def fake_completion(model, messages, **kw):
        if "sonnet" in model:
            raise ValueError("primary: invalid model string")
        raise ValueError("fallback: connection refused")

    with patch("app.llm.litellm.completion", side_effect=fake_completion), pytest.raises(
        ValueError, match="primary: invalid model string"
    ):
        llm.chat([{"role": "user", "content": "hi"}], model="openrouter/x/claude-sonnet-5")


def test_complete_defaults_num_retries_for_transient_errors():
    """OpenRouter (and other providers) rate-limit in short bursts; litellm's own
    num_retries handles backoff for RateLimitError/5xx/timeouts. Regression: found via a
    live CI run hitting OpenRouter's new-account 20rpm cap with no retry at all."""
    from app.llm import _complete

    seen = {}

    def fake_completion(model, messages, **kw):
        seen.update(kw)
        return _Resp("ok")

    with patch("app.llm.litellm.completion", side_effect=fake_completion):
        _complete("anthropic/claude-sonnet-5", [{"role": "user", "content": "hi"}], {})
    assert seen.get("num_retries") == 3


def test_complete_respects_explicit_num_retries():
    from app.llm import _complete

    seen = {}

    def fake_completion(model, messages, **kw):
        seen.update(kw)
        return _Resp("ok")

    with patch("app.llm.litellm.completion", side_effect=fake_completion):
        _complete("anthropic/claude-sonnet-5", [{"role": "user", "content": "hi"}],
                  {"num_retries": 5})
    assert seen.get("num_retries") == 5


def test_chat_defaults_a_reasonable_max_tokens():
    """Regression: found via a live CI run against OpenRouter, which preflight-checks
    cost against max_tokens and rejects the call if the account can't cover the model's
    full window (65536 for claude-sonnet-5) even when actual usage would be tiny."""
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
