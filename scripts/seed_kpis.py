"""Synthetic KPI data (72h, 15-min) for 3 cells, each with a different injected fault
in the last 4 hours:
  CELL_001  prb_utilization_pct      spikes (+30)
  CELL_002  rrc_setup_success_rate   drops (-8 points)
  CELL_003  handover_success_rate    drops (-10 points)
Every cell gets all three KPIs; only the named one is faulty."""
import datetime as dt
import math
import os
import random

import psycopg

url = os.getenv("DATABASE_URL", "postgresql://telecom:telecom@localhost:5432/telecom")
now = dt.datetime.now(dt.UTC)
steps = 72 * 4
faulty_from = steps - 16
FAULTS = {
    ("CELL_001", "prb_utilization_pct"): +30.0,
    ("CELL_002", "rrc_setup_success_rate"): -8.0,
    ("CELL_003", "handover_success_rate"): -10.0,
}
BASE = {"prb_utilization_pct": (55.0, 15.0), "rrc_setup_success_rate": (99.3, 0.3),
        "handover_success_rate": (98.5, 0.4)}

rows = []
for cell in ("CELL_001", "CELL_002", "CELL_003"):
    for kpi, (base, amp) in BASE.items():
        for i in range(steps):
            ts = now - dt.timedelta(minutes=15 * (steps - i))
            v = base + amp * math.sin(2 * math.pi * ts.hour / 24) + random.gauss(0, amp * 0.1)
            if i >= faulty_from:
                v += FAULTS.get((cell, kpi), 0.0)
            v = min(v, 100.0) if kpi != "prb_utilization_pct" else max(0.0, min(v, 100.0))
            rows.append((ts, cell, kpi, v))

with psycopg.connect(url) as conn, conn.cursor() as cur:
    cur.execute("DELETE FROM kpis")
    cur.executemany("INSERT INTO kpis (ts, cell_id, kpi, value) VALUES (%s,%s,%s,%s)", rows)
print(f"inserted {len(rows)} rows")
