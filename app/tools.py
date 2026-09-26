import json

import psycopg

from .config import settings
from .db import get_pool
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


def create_ticket(thread_id: str, alert: dict, diagnosis: str) -> dict:
    """Write action. Persists to the tickets table. Only called after human approval."""
    with get_pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO tickets (thread_id, cell_id, kpi, alert, diagnosis) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at",
            (thread_id, alert["cell_id"], alert["kpi"], json.dumps(alert), diagnosis),
        ).fetchone()
    return {
        "id": f"INC-{row[0]}",
        "thread_id": thread_id,
        "alert": alert,
        "diagnosis": diagnosis,
        "created_at": row[1].isoformat(),
    }


def get_ticket(ticket_id: str) -> dict | None:
    """Look up a ticket by its external id (e.g. 'INC-42')."""
    try:
        pk = int(ticket_id.removeprefix("INC-"))
    except ValueError:
        return None
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT id, thread_id, cell_id, kpi, alert, diagnosis, created_at "
            "FROM tickets WHERE id = %s", (pk,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": f"INC-{row[0]}", "thread_id": row[1], "cell_id": row[2], "kpi": row[3],
        "alert": row[4], "diagnosis": row[5], "created_at": row[6].isoformat(),
    }
