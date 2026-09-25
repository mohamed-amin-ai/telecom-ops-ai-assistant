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
