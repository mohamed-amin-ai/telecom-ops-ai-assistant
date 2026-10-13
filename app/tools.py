import hashlib
import hmac
import json
import logging
import re
import time
from datetime import UTC, datetime

import httpx
import psycopg

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
    return profile_series(get_kpis(cell_id, kpi, lookback_hours), recent_hours,
                          now=datetime.now(UTC))


def webhook_payload(ticket: dict) -> dict:
    """The body sent to the ITSM endpoint. "jira" maps a ticket onto a Jira REST v2 issue; the
    external id goes in a label (INC-42) so a retry or a human can find the issue again."""
    if settings.ticket_webhook_format != "jira":
        return ticket
    alert = ticket.get("alert") or {}
    return {"fields": {
        "project": {"key": settings.jira_project_key},
        "issuetype": {"name": settings.jira_issue_type},
        "summary": f"[{ticket['id']}] {alert.get('cell_id', '?')} {alert.get('kpi', '')}"[:250],
        "labels": [ticket["id"], "telecom-ops-assistant"],
        "description": (
            f"Approved by: {ticket.get('approved_by') or 'unknown'}\n"
            f"Alert: {alert}\n\nDiagnosis:\n{ticket.get('diagnosis', '')}")[:30000],
    }}


def deliver_ticket_webhook(ticket: dict) -> str | None:
    """POST an approved ticket to the configured ITSM endpoint. Returns a status string, or
    None if no webhook is configured. Retries transient failures with backoff; never raises,
    because the ticket already exists and a flaky downstream must not undo an approval."""
    url = settings.ticket_webhook_url
    if not url:
        return None
    body = json.dumps(webhook_payload(ticket), default=str).encode()
    headers = {"Content-Type": "application/json", "Idempotency-Key": ticket["id"]}
    if settings.ticket_webhook_auth:
        headers["Authorization"] = settings.ticket_webhook_auth
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


def _ticket_dict(row, thread_id, alert, diagnosis, approved_by) -> dict:
    return {"id": f"INC-{row[0]}", "thread_id": thread_id, "alert": alert,
            "diagnosis": diagnosis, "approved_by": approved_by,
            "created_at": row[1].isoformat()}


def _existing_ticket(conn, thread_id: str):
    return conn.execute("SELECT id, created_at, approved_by, webhook_status FROM tickets "
                        "WHERE thread_id = %s ORDER BY id LIMIT 1", (thread_id,)).fetchone()


def create_ticket(thread_id: str, alert: dict, diagnosis: str,
                  approved_by: str | None = None) -> dict:
    """Write action. Persists to the tickets table. Only called after human approval.
    Idempotent per incident (thread): a retried graph step (e.g. after a crash between the
    INSERT and the next node) returns the existing ticket instead of creating a second one."""
    with get_pool().connection() as conn:
        row = _existing_ticket(conn, thread_id)
        if row is None:
            try:
                row = conn.execute(
                    "INSERT INTO tickets (thread_id, cell_id, kpi, alert, diagnosis, approved_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at",
                    (thread_id, alert["cell_id"], alert["kpi"], json.dumps(alert), diagnosis,
                     approved_by),
                ).fetchone()
            except psycopg.errors.UniqueViolation:  # lost a race with a concurrent retry
                conn.rollback()
                row = _existing_ticket(conn, thread_id)
                return _ticket_dict(row, thread_id, alert, diagnosis, row[2])
        else:
            log.info("ticket for %s already exists (INC-%s); not creating another", thread_id, row[0])
            return _ticket_dict(row, thread_id, alert, diagnosis, row[2])
    ticket = _ticket_dict(row, thread_id, alert, diagnosis, approved_by)
    metrics.TICKETS.inc()
    status = deliver_ticket_webhook(ticket)
    if status:
        metrics.WEBHOOK.labels("delivered" if status == "delivered" else "failed").inc()
        with get_pool().connection() as conn:
            conn.execute("UPDATE tickets SET webhook_status = %s WHERE id = %s", (status, row[0]))
        ticket["webhook_status"] = status
    return ticket


_SEVERITY = re.compile(r"Severity:\s*(P[1-4]|undetermined)", re.IGNORECASE)


def _severity_of(diagnosis: str) -> str | None:
    m = _SEVERITY.findall(diagnosis or "")
    return m[-1].upper() if m and m[-1].upper().startswith("P") else (m[-1].lower() if m else None)


def ticket_history(cell_id: str, limit: int = 5) -> list[dict]:
    """Read-only: the most recent past tickets for a cell (newest first). Returns facts only
    (id, KPI, time, severity, approver), not the stored diagnosis text: a small model repeats
    an earlier diagnosis, including its numbers, as if it described the current incident."""
    limit = max(1, min(int(limit), 10))
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, kpi, diagnosis, created_at, approved_by FROM tickets "
            "WHERE cell_id = %s ORDER BY created_at DESC LIMIT %s", (cell_id, limit)).fetchall()
    return [{"id": f"INC-{r[0]}", "kpi": r[1], "severity": _severity_of(r[2] or ""),
             "created_at": r[3].isoformat(), "approved_by": r[4]} for r in rows]


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


def redeliver_failed(limit: int = 50) -> dict:
    """Dead-letter sweep: retry tickets whose hand-off failed (webhook_status 'failed:...'),
    oldest first, with the same Idempotency-Key so a receiver that did get an earlier attempt
    can de-duplicate. Run it on a schedule (cron / k8s CronJob) -- see docs/oncall.md."""
    with get_pool().connection() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM tickets WHERE webhook_status LIKE 'failed%%' ORDER BY id LIMIT %s",
            (max(1, min(int(limit), 500)),)).fetchall()]
    done = failed = 0
    for pk in ids:
        ticket = get_ticket(f"INC-{pk}")
        if ticket is None:
            continue
        status = deliver_ticket_webhook(ticket)
        if status is None:
            return {"retried": 0, "delivered": 0, "failed": 0, "note": "no webhook configured"}
        with get_pool().connection() as conn:
            conn.execute("UPDATE tickets SET webhook_status = %s WHERE id = %s", (status, pk))
        metrics.WEBHOOK.labels("delivered" if status == "delivered" else "failed").inc()
        done += status == "delivered"
        failed += status != "delivered"
    return {"retried": len(ids), "delivered": done, "failed": failed}
