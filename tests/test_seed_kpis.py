import datetime as dt

import pytest

from app.stats import profile_series
from scripts.seed_kpis import FAULTS, generate


def _profiles(now, seed):
    rows = generate(now, seed)
    out = {}
    for cell, kpi in {(r[1], r[2]) for r in rows}:
        pts = sorted(({"ts": r[0].isoformat(), "value": r[3]} for r in rows
                      if r[1] == cell and r[2] == kpi), key=lambda p: p["ts"])
        out[(cell, kpi)] = profile_series(pts)
    return out


# Every weekday x every hour of the day x two seeds. An earlier version of this test sampled only
# 4 hours and missed that the PRB fault went undetected at ~46% of hours (a Kaggle run exposed it).
@pytest.mark.parametrize("seed", [7, 42])
@pytest.mark.parametrize("day", range(7))
def test_only_injected_faults_are_anomalous(day, seed):
    for hour in range(24):
        now = dt.datetime(2026, 10, 5 + day, hour, 23, tzinfo=dt.UTC)
        flagged = {k for k, p in _profiles(now, seed).items() if p.get("anomalous")}
        assert flagged == set(FAULTS), (day, hour, flagged)


def test_shape_is_not_a_plain_sine():
    rows = [r for r in generate(dt.datetime(2026, 10, 7, 12, tzinfo=dt.UTC), 7)
            if r[1] == "CELL_001" and r[2] == "prb_utilization_pct"]
    by_hour = {}
    for ts, _, _, v in rows[:200]:
        by_hour.setdefault(ts.hour, []).append(v)
    mean = {h: sum(v) / len(v) for h, v in by_hour.items()}
    assert mean[20] > mean[11] > mean[4] + 20      # evening peak > morning peak > night
    assert len(rows) < 288                          # some samples are missing
