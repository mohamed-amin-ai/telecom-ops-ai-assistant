"""Append-only audit trail (the table rejects UPDATE and DELETE). Recording an approval
decision is fail-closed: if the audit insert fails, the request fails and nothing happens."""
import json

from .db import get_pool


def record(actor: str, action: str, thread_id: str | None = None, **detail) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO audit_log (actor, action, thread_id, detail) VALUES (%s, %s, %s, %s)",
            (actor, action, thread_id, json.dumps(detail, default=str)),
        )


def recent(thread_id: str | None = None, limit: int = 100) -> list[dict]:
    q = "SELECT id, ts, actor, action, thread_id, detail FROM audit_log"
    args: tuple = ()
    if thread_id:
        q += " WHERE thread_id = %s"
        args = (thread_id,)
    q += " ORDER BY id DESC LIMIT %s"
    with get_pool().connection() as conn:
        rows = conn.execute(q, (*args, min(limit, 500))).fetchall()
    return [{"id": r[0], "ts": r[1].isoformat(), "actor": r[2], "action": r[3],
             "thread_id": r[4], "detail": r[5]} for r in rows]
