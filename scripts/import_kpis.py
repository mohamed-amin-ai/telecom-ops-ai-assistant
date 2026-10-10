"""Load a real KPI export (CSV) into the kpis table, replacing the synthetic seed.

Long format  (ts,cell_id,kpi,value):
  python -m scripts.import_kpis export.csv
Wide format (one column per KPI, e.g. an OSS/PM export):
  python -m scripts.import_kpis export.csv --wide --ts-col time --cell-col cell \
      --kpi-cols prb_utilization_pct,rrc_setup_success_rate,handover_success_rate
Rename vendor columns on the fly with --rename "DL PRB Util=prb_utilization_pct".
Use --append to keep existing rows. Rows with an unparsable timestamp or value are skipped
and counted; the script exits non-zero if more than 5% are bad."""
import argparse
import csv
import datetime as dt
import os
import sys


def parse_ts(v: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(v.strip().replace("Z", "+00:00"))  # noqa: FURB162
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def read_rows(path, wide=False, ts_col="ts", cell_col="cell_id", kpi_cols=(), rename=None):
    rename = rename or {}
    rows, bad = [], 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {rename.get(k, k): v for k, v in r.items()}
            try:
                ts = parse_ts(r[ts_col])
                cell = r[cell_col].strip()
                if wide:
                    pairs = [(k, float(r[k])) for k in kpi_cols if r.get(k, "") != ""]
                else:
                    pairs = [(r["kpi"].strip(), float(r["value"]))]
            except (KeyError, ValueError, AttributeError):
                bad += 1
                continue
            rows += [(ts, cell, k, v) for k, v in pairs]
    return rows, bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--wide", action="store_true")
    ap.add_argument("--ts-col", default="ts")
    ap.add_argument("--cell-col", default="cell_id")
    ap.add_argument("--kpi-cols", default="")
    ap.add_argument("--rename", action="append", default=[])
    ap.add_argument("--append", action="store_true")
    a = ap.parse_args(argv)
    rename = dict(x.split("=", 1) for x in a.rename)
    cols = [c for c in a.kpi_cols.split(",") if c]
    if a.wide and not cols:
        sys.exit("--wide needs --kpi-cols")
    rows, bad = read_rows(a.csv, a.wide, a.ts_col, a.cell_col, cols, rename)
    total = len(rows) + bad
    if not rows or bad > 0.05 * total:
        sys.exit(f"refusing to load: {len(rows)} good rows, {bad} bad")
    import psycopg
    url = os.getenv("DATABASE_URL", "postgresql://telecom:telecom@localhost:5432/telecom")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        if not a.append:
            cur.execute("DELETE FROM kpis")
        cur.executemany("INSERT INTO kpis (ts, cell_id, kpi, value) VALUES (%s,%s,%s,%s)", rows)
    print(f"inserted {len(rows)} rows ({bad} skipped)")


if __name__ == "__main__":
    main()
