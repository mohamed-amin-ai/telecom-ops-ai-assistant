from datetime import datetime, timedelta
from statistics import mean, pstdev


def profile_series(points: list[dict], recent_hours: int = 4) -> dict:
    """Compare the most recent window with the same hours-of-day earlier in the series.
    points: [{"ts": iso8601, "value": float}, ...] ordered by ts."""
    parsed = [(datetime.fromisoformat(p["ts"]), p["value"]) for p in points
              if p["value"] is not None]
    if len(parsed) < 8:
        return {"n": len(parsed), "note": "insufficient data"}
    end = parsed[-1][0]
    cutoff = end - timedelta(hours=recent_hours)
    recent = [v for t, v in parsed if t > cutoff]
    hours = {t.hour for t, _ in parsed if t > cutoff}
    base = [v for t, v in parsed if t <= cutoff and t.hour in hours]
    if len(base) < 4:
        base = [v for t, v in parsed if t <= cutoff]
    if not recent or not base:
        return {"n": len(parsed), "note": "insufficient data"}
    b_mean, b_sd = mean(base), pstdev(base)
    # Floor at 1% of the baseline level: avoids absurd z on near-flat series while still
    # letting a few points of drop register on ratio KPIs that sit near 100%.
    scale = max(b_sd, 0.01 * abs(b_mean), 1e-6)
    z = (mean(recent) - b_mean) / scale
    return {
        "n": len(parsed),
        "baseline_mean": round(b_mean, 2),
        "baseline_std": round(b_sd, 2),
        "recent_mean": round(mean(recent), 2),
        "recent_max": round(max(recent), 2),
        "recent_min": round(min(recent), 2),
        "last": round(parsed[-1][1], 2),
        "z_score": round(z, 2),
        "anomalous": abs(z) >= 3,
    }
