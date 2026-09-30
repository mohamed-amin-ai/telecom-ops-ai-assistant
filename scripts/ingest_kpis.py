"""Load KPI measurements from a CSV into TimescaleDB. Idempotent: re-loading the same file
adds nothing (unique index on cell_id, kpi, ts). Bad rows are counted and skipped, not fatal.

Long format (default):  ts,cell_id,kpi,value
Wide format (--wide):   ts,cell_id,<kpi_1>,<kpi_2>,...   (every other column is a KPI)

  python -m scripts.ingest_kpis data.csv [--wide]

Timestamps are ISO-8601; ones without a timezone are taken as UTC."""
import argparse
import csv
import math
import re
from datetime import datetime, timezone

from app.db import get_pool

CELL = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
KPI = re.compile(r"^[a-z0-9_]{1,64}$")


def parse_ts(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def rows_from_csv(path: str, wide: bool):
    """Yield (ts, cell_id, kpi, value) tuples and a list of (line_no, reason) rejects."""
    good, bad = [], []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for n, r in enumerate(reader, start=2):
            try:
                ts, cell = parse_ts(r["ts"]), r["cell_id"].strip()
                if not CELL.match(cell):
                    raise ValueError(f"bad cell_id {cell!r}")
                pairs = ([(r["kpi"].strip(), r["value"])] if not wide else
                         [(k, v) for k, v in r.items() if k not in ("ts", "cell_id")])
                for kpi, raw in pairs:
                    if not KPI.match(kpi):
                        raise ValueError(f"bad kpi name {kpi!r}")
                    if raw is None or raw.strip() == "":
                        continue  # a blank cell in wide format just means "no reading"
                    v = float(raw)
                    if not math.isfinite(v):
                        raise ValueError("non-finite value")
                    good.append((ts, cell, kpi, v))
            except (KeyError, ValueError, TypeError) as e:
                bad.append((n, str(e)))
    return good, bad


def load(path: str, wide: bool = False) -> dict:
    good, bad = rows_from_csv(path, wide)
    with get_pool().connection() as conn:
        before = conn.execute("SELECT count(*) FROM kpis").fetchone()[0]
        with conn.cursor() as cur:
            for i in range(0, len(good), 5000):
                cur.executemany(
                    "INSERT INTO kpis (ts, cell_id, kpi, value) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING", good[i:i + 5000])
        after = conn.execute("SELECT count(*) FROM kpis").fetchone()[0]
    return {"parsed": len(good), "inserted": after - before,
            "skipped_duplicates": len(good) - (after - before),
            "rejected": len(bad), "rejects": bad[:10]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--wide", action="store_true")
    a = ap.parse_args()
    print(load(a.csv, a.wide))
