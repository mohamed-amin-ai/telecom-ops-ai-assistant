"""Synthetic KPI data (72h, 15-min) for 3 cells with realistic shape, plus one injected fault each
in the last 4 hours:
  CELL_001  prb_utilization_pct      spikes (+30)
  CELL_002  rrc_setup_success_rate   drops (-8 points)
  CELL_003  handover_success_rate    drops (-10 points)
Every cell gets all three KPIs; only the named one is faulty.

Realism (still synthetic, not operator data): a two-peak daily traffic profile (late-morning and
evening busy hours, night trough), a weekend dip, a per-cell load character (urban / suburban /
residential), correlated autocorrelated noise, success rates that sag slightly under high load,
a few missing samples, and a few benign one-sample blips that are not faults. Missing samples
and blips are kept out of the last 8 hours so the injected faults stay the only recent anomaly."""
import datetime as dt
import math
import os
import random

STEPS = 72 * 4
FAULTY_FROM = STEPS - 16
FAULTS = {
    ("CELL_001", "prb_utilization_pct"): +30.0,
    ("CELL_002", "rrc_setup_success_rate"): -8.0,
    ("CELL_003", "handover_success_rate"): -10.0,
}
# load_scale, peak weights (morning, evening), noise level
CELLS = {
    "CELL_001": (0.78, (0.9, 1.0), 1.0),   # dense urban: heavy, evening-led (peak ~65%, headroom for the +30 fault)
    "CELL_002": (0.70, (1.0, 0.8), 0.9),   # suburban: commuter-ish
    "CELL_003": (0.55, (0.5, 1.0), 1.1),   # residential: evening
}
BASE = {"prb_utilization_pct": 55.0, "rrc_setup_success_rate": 99.3, "handover_success_rate": 98.5}


def _bump(h: float, centre: float, width: float) -> float:
    d = min(abs(h - centre), 24 - abs(h - centre))
    return math.exp(-(d / width) ** 2)


def load_profile(ts: dt.datetime, weights: tuple[float, float]) -> float:
    """0..1 traffic shape: night trough ~0.12, peaks around 11:30 and 20:30."""
    h = ts.hour + ts.minute / 60
    shape = 0.12 + 0.55 * weights[0] * _bump(h, 11.5, 3.0) + 0.75 * weights[1] * _bump(h, 20.5, 3.2)
    if ts.weekday() >= 5:
        shape *= 0.95
    return min(shape, 1.0)


def generate(now: dt.datetime, seed: int = 7) -> list[tuple]:
    rng = random.Random(seed)
    rows = []
    for cell, (scale, weights, noise) in CELLS.items():
        state = {k: 0.0 for k in BASE}
        for i in range(STEPS):
            ts = now - dt.timedelta(minutes=15 * (STEPS - i))
            shape = load_profile(ts, weights)
            load = min(95.0, 8 + 78 * scale * shape)
            safe = i < STEPS - 32          # missing samples / blips only in the older history
            for kpi in BASE:  # noqa: PLC0206
                state[kpi] = 0.7 * state[kpi] + rng.gauss(0, 1)   # AR(1) noise
                n = state[kpi] * noise
                if kpi == "prb_utilization_pct":
                    v = load + 2.2 * n
                elif kpi == "rrc_setup_success_rate":
                    v = BASE[kpi] - 0.35 * max(0.0, load - 70) / 25 + 0.07 * n
                else:
                    v = BASE[kpi] - 0.5 * max(0.0, load - 65) / 30 + 0.12 * n
                if safe and rng.random() < 0.004:
                    v += rng.choice((-1, 1)) * (6 if kpi == "prb_utilization_pct" else 0.8)
                if i >= FAULTY_FROM:
                    v += FAULTS.get((cell, kpi), 0.0)
                v = max(0.0, min(v, 100.0))
                if safe and rng.random() < 0.006:
                    continue                      # missing sample
                rows.append((ts, cell, kpi, round(v, 3)))
    return rows


def main():
    import psycopg
    url = os.getenv("DATABASE_URL", "postgresql://telecom:telecom@localhost:5432/telecom")
    rows = generate(dt.datetime.now(dt.UTC), seed=int(os.getenv("SEED", "7")))
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM kpis")
        cur.executemany("INSERT INTO kpis (ts, cell_id, kpi, value) VALUES (%s,%s,%s,%s)", rows)
    print(f"inserted {len(rows)} rows")


if __name__ == "__main__":
    main()
