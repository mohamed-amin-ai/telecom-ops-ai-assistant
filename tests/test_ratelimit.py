from app.ratelimit import _allow_local


def test_allows_up_to_the_limit():
    results = [_allow_local("k1", limit=3, window=60) for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_separate_keys_have_separate_budgets():
    for _ in range(3):
        _allow_local("k2a", limit=3, window=60)
    assert _allow_local("k2b", limit=3, window=60) is True


def test_window_expiry_frees_up_budget():
    import time
    from unittest.mock import patch

    calls = iter([0.0, 0.0, 0.0, 100.0])  # 3 requests at t=0, 1 more at t=100 (window=60)
    with patch.object(time, "monotonic", lambda: next(calls)):
        results = [_allow_local("k3", limit=3, window=60) for _ in range(4)]
    assert results == [True, True, True, True]
