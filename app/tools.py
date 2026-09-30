import hashlib
import hmac
import json
import logging
import time

import httpx

from . import metrics
from .config import settings
from .db import get_pool
from .stats import profile_series

log = logging.getLogger("tools")


def get_kpis(cell_id: str, kpi: str, hours: int = 24) -> list[dict]:
    """Read-only KPI time series from TimescaleDB."""
    with get_pool().connection() as conn:
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


def deliver_ticket_webhook(ticket: dict) -> str | None:
    """POST an approved ticket to the configured ITSM endpoint. Returns a status string, or
    None if no webhook is configured. Retries transient failures with backoff; never raises,
    because the ticket already exists and a flaky downstream must not undo an approval."""
    url = settings.ticket_webhook_url
    if not url:
        return None
    body = json.dumps(ticket, default=str).encode()
    headers = {"Content-Type": "application/json", "Idempotency-Key": ticket["id"]}
    if settings.ticket_webhook_secret:
        digest = hmac.new(settings.ticket_webhook_secret.encode(), body, hashlib.sha256)
        headers["X-Signature-256"] = "sha256=" + digest.hexdigest()
    status = "failed:unreachable"
    for attempt in range(3):
        try:
            r = httpx.post(url, content=body, headers=headers, timeout=5)
            if r.status_code < 300:
                return "delivered"
            status = f"failed:{r.status_code}"
            if r.status_code < 500 and r.status_code != 429:
                break  # a 4xx won't get better by retrying
        except httpx.HTTPError as e:
            status = f"failed:{type(e).__name__}"
        time.sleep(0.5 * 2**attempt)
    log.warning("ticket webhook delivery failed for %s: %s", ticket["id"], status)
    return status


def create_ticket(thread_id: str, alert: dict, diagnosis: str,
                  approved_by: str | None = None) -> dict:
    """Write action. Persists to the tickets table. Only called after human approval."""
    with get_pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO tickets (thread_id, cell_id, kpi, alert, diagnosis, approved_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at",
            (thread_id, alert["cell_id"], alert["kpi"], json.dumps(alert), diagnosis,
             approved_by),
        ).fetchone()
    ticket = {
        "id": f"INC-{row[0]}",
        "thread_id": thread_id,
        "alert": alert,
        "diagnosis": diagnosis,
        "approved_by": approved_by,
        "created_at": row[1].isoformat(),
    }
    metrics.TICKETS.inc()
    status = deliver_ticket_webhook(ticket)
    if status:
        with get_pool().connection() as conn:
            conn.execute("UPDATE tickets SET webhook_status = %s WHERE id = %s", (status, row[0]))
        ticket["webhook_status"] = status
    return ticket


def get_ticket(ticket_id: str) -> dict | None:
    """Look up a ticket by its external id (e.g. 'INC-42')."""
    try:
        pk = int(ticket_id.removeprefix("INC-"))
    except ValueError:
        return None
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT id, thread_id, cell_id, kpi, alert, diagnosis, created_at, approved_by, "
            "webhook_status FROM tickets WHERE id = %s", (pk,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": f"INC-{row[0]}", "thread_id": row[1], "cell_id": row[2], "kpi": row[3],
        "alert": row[4], "diagnosis": row[5], "created_at": row[6].isoformat(),
        "approved_by": row[7], "webhook_status": row[8],
    }
