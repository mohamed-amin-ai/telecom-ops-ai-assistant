import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from .config import settings
from .stats import profile_series


def get_kpis(cell_id: str, kpi: str, hours: int = 24) -> list[dict]:
    """Read-only KPI time series from TimescaleDB."""
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute(
            "SELECT ts, value FROM kpis WHERE cell_id = %s AND kpi = %s "
            "AND ts > now() - make_interval(hours => %s::int) ORDER BY ts",
            (cell_id, kpi, hours),
        ).fetchall()
    return [{"ts": r[0].isoformat(), "value": r[1]} for r in rows]


def kpi_profile(cell_id: str, kpi: str, lookback_hours: int = 72,
                recent_hours: int = 4) -> dict:
    """Recent window vs same-hour baseline (z-score). Local, no external service."""
    return profile_series(get_kpis(cell_id, kpi, lookback_hours), recent_hours)


def create_ticket(alert: dict, diagnosis: str) -> dict:
    """Write action. Appends to data/tickets.jsonl. Only called after human approval."""
    ticket = {
        "id": f"INC-{int(datetime.now(timezone.utc).timestamp())}",
        "alert": alert,
        "diagnosis": diagnosis,
    }
    path = Path("data/tickets.jsonl")
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(ticket) + "\n")
    return ticket
