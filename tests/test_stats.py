import math
import random
from datetime import UTC, datetime, timedelta

from app.stats import profile_series


def _series(base=55.0, amp=15.0, noise=1.5, delta=0.0, hours=72):
    random.seed(0)
    end = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    steps = hours * 4
    pts = []
    for i in range(steps):
        ts = end - timedelta(minutes=15 * (steps - 1 - i))
        v = base + amp * math.sin(2 * math.pi * ts.hour / 24) + random.gauss(0, noise)
        if i >= steps - 16:
            v += delta
        pts.append({"ts": ts.isoformat(), "value": v})
    return pts


def test_detects_spike():
    p = profile_series(_series(delta=30))
    assert p["anomalous"] and p["z_score"] > 3


def test_normal_series_not_flagged():
    assert not profile_series(_series())["anomalous"]


def test_detects_drop_on_ratio_kpi_near_100():
    # Regression: an 8-point RRC SSR drop on a ~99.5% KPI must be flagged.
    p = profile_series(_series(base=99.5, amp=0.3, noise=0.03, delta=-8))
    assert p["anomalous"] and p["z_score"] < -3


def test_healthy_ratio_kpi_not_flagged():
    assert not profile_series(_series(base=99.5, amp=0.3, noise=0.03))["anomalous"]


def test_insufficient_data():
    assert profile_series([])["note"] == "insufficient data"


def test_nan_and_inf_values_are_ignored_not_propagated():
    pts = _series(delta=30)
    pts[-1]["value"] = float("nan")
    pts[-5]["value"] = float("inf")
    p = profile_series(pts)
    assert math.isfinite(p["z_score"]) and p["anomalous"]


def test_silent_cell_is_flagged_instead_of_looking_healthy():
    pts = _series()                                       # last point 2026-01-10 12:00
    now = datetime(2026, 1, 10, 22, 0, tzinfo=UTC)        # feed silent for 10 hours
    p = profile_series(pts, now=now)
    assert p["anomalous"] and p["stale_minutes"] == 600 and "silent" in p["note"]
    fresh = profile_series(pts, now=datetime(2026, 1, 10, 12, 20, tzinfo=UTC))
    assert not fresh["anomalous"] and "stale_minutes" not in fresh
