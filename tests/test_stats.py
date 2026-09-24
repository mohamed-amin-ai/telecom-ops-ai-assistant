import math
import random
from datetime import datetime, timedelta, timezone

from app.stats import profile_series


def _series(spike: float, hours: int = 72):
    random.seed(0)
    end = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    pts = []
    steps = hours * 4
    for i in range(steps):
        ts = end - timedelta(minutes=15 * (steps - 1 - i))
        v = 55 + 15 * math.sin(2 * math.pi * ts.hour / 24) + random.gauss(0, 1.5)
        if i >= steps - 16:
            v += spike
        pts.append({"ts": ts.isoformat(), "value": v})
    return pts


def test_detects_spike():
    p = profile_series(_series(spike=30))
    assert p["anomalous"] and p["z_score"] > 3


def test_normal_series_not_flagged():
    p = profile_series(_series(spike=0))
    assert not p["anomalous"]


def test_insufficient_data():
    assert profile_series([])["note"] == "insufficient data"
