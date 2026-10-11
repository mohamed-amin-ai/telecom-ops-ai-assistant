from datetime import datetime, timedelta
from statistics import mean, pstdev


def _slot(t: datetime) -> int:
    return t.hour * 4 + t.minute // 15      # 15-minute time-of-day bucket


def _residual_profile(parsed, cutoff):
    """Time-of-day baseline: each recent point is compared with the same 15-minute slot on
    earlier days, and the noise scale is the day-to-day scatter at a fixed slot. The older
    approach pooled every baseline value from the same hours, so the daily ramp inside a
    4-hour window inflated the spread and hid real spikes (a +30 PRB jump scored z=2.2)."""
    by_slot: dict[int, list[float]] = {}
    for t, v in parsed:
        if t <= cutoff:
            by_slot.setdefault(_slot(t), []).append(v)
    recent = [(t, v) for t, v in parsed if t > cutoff and len(by_slot.get(_slot(t), [])) >= 2]
    sq, dof = 0.0, 0
    for vals in by_slot.values():
        if len(vals) >= 2:
            m = mean(vals)
            sq += sum((x - m) ** 2 for x in vals)
            dof += len(vals) - 1
    if len(recent) < 4 or dof < 8:
        return None
    noise = (sq / dof) ** 0.5
    base_means = [mean(by_slot[_slot(t)]) for t, _ in recent]
    resid = [v - bm for (_, v), bm in zip(recent, base_means, strict=True)]
    return noise, mean(base_means), [v for _, v in recent], mean(resid)


def profile_series(points: list[dict], recent_hours: int = 4) -> dict:
    """Compare the most recent window with the same time of day on earlier days.
    points: [{"ts": iso8601, "value": float}, ...] ordered by ts."""
    parsed = [(datetime.fromisoformat(p["ts"]), p["value"]) for p in points
              if p["value"] is not None]
    if len(parsed) < 8:
        return {"n": len(parsed), "note": "insufficient data"}
    end = parsed[-1][0]
    cutoff = end - timedelta(hours=recent_hours)
    res = _residual_profile(parsed, cutoff)
    if res is not None:
        noise, b_mean, recent, mean_resid = res
        # Floor at 1% of the baseline level: avoids absurd z on near-flat series while still
        # letting a few points of drop register on ratio KPIs that sit near 100%.
        scale = max(noise, 0.01 * abs(b_mean), 1e-6)
        z = mean_resid / scale
        return {
            "n": len(parsed),
            "baseline_mean": round(b_mean, 2),
            "baseline_std": round(noise, 2),
            "recent_mean": round(mean(recent), 2),
            "recent_max": round(max(recent), 2),
            "recent_min": round(min(recent), 2),
            "last": round(parsed[-1][1], 2),
            "z_score": round(z, 2),
            "anomalous": abs(z) >= 3,
        }
    return _pooled_profile(parsed, cutoff)


def _pooled_profile(parsed, cutoff) -> dict:
    """Fallback when there are not enough days for a per-slot baseline (short history)."""
    recent = [v for t, v in parsed if t > cutoff]
    hours = {t.hour for t, _ in parsed if t > cutoff}
    base = [v for t, v in parsed if t <= cutoff and t.hour in hours]
    if len(base) < 4:
        base = [v for t, v in parsed if t <= cutoff]
    if not recent or not base:
        return {"n": len(parsed), "note": "insufficient data"}
    b_mean, b_sd = mean(base), pstdev(base)
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
