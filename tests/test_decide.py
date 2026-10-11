"""/decision logic with a fake graph and DB: no ticket without a pending approval, a retry of a
failed later step may only repeat the SAME decision, and the ticket is created at most once."""
import dataclasses
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, tools

TID = str(uuid.uuid4())


class Conn:
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, q, args=()):
        class R:
            def fetchone(s): return (True,) if "advisory_lock" in q else (5.0,)
        return R()


class FakeGraph:
    def __init__(self, nxt, approved):
        self.nxt, self.approved, self.invoked = nxt, approved, []

    def get_state(self, cfg):
        return SimpleNamespace(next=self.nxt, values={"alert": {"cell_id": "C"},
                                                      "approved": self.approved})

    def invoke(self, cmd, cfg):
        self.invoked.append(cmd)
        return {"ticket": {"id": "INC-1"}, "diagnosis": "d"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "settings", dataclasses.replace(
        main.settings, auth_required=False, rate_limit_per_min=0, ip_rate_limit_per_min=0))
    from app import auth
    monkeypatch.setattr(auth, "settings", main.settings)
    monkeypatch.setattr(main, "get_pool", lambda: SimpleNamespace(connection=lambda: Conn()))
    log = []
    monkeypatch.setattr(main.audit, "record", lambda *a, **k: log.append((a[1], k)))

    def make(graph):
        monkeypatch.setattr(main, "graph", graph)
        return TestClient(main.app), log
    return make


def post(c, approve):
    return c.post(f"/incident/{TID}/decision", json={"approve": approve})


def test_normal_decision_resumes_the_pending_approval(client):
    g = FakeGraph(("approval",), approved=None)
    c, log = client(g)
    assert post(c, True).status_code == 200
    assert len(g.invoked) == 1 and g.invoked[0].resume == {"approve": True, "by": "anonymous"}
    assert next(a for a, _ in log) == "decision"


def test_reject_retry_cannot_create_a_ticket_after_a_failed_ticket_step(client):
    """Approved, then the ticket step crashed: the checkpoint waits on 'ticket'. A second
    approver sending reject must NOT be able to resume it (the old code ignored the resume
    value and created the ticket while auditing 'approve=false')."""
    g = FakeGraph(("ticket",), approved=True)
    c, log = client(g)
    r = post(c, False)
    assert r.status_code == 409 and g.invoked == []
    assert all(a != "decision" for a, _ in log)


def test_same_decision_retry_continues_the_failed_step_once(client):
    g = FakeGraph(("ticket",), approved=True)
    c, log = client(g)
    assert post(c, True).status_code == 200
    assert g.invoked == [None]                      # continue from the checkpoint, no new decision
    assert next(a for a, _ in log) == "decision_retry"


def test_cannot_resurrect_a_rejection_by_retrying_with_approve(client):
    g = FakeGraph(("report",), approved=False)
    c, _ = client(g)
    assert post(c, True).status_code == 409 and g.invoked == []


def test_finished_or_unknown_incident(client):
    c, _ = client(FakeGraph((), approved=True))
    assert post(c, True).status_code == 409
    assert c.post("/incident/not-a-uuid/decision", json={"approve": True}).status_code == 404


def test_audit_failure_after_ticket_creation_is_not_a_500(client, monkeypatch):
    import psycopg
    g = FakeGraph(("approval",), approved=None)
    c, _ = client(g)

    def rec(actor, action, *a, **k):
        if action == "ticket_created":
            raise psycopg.OperationalError("audit down")
    monkeypatch.setattr(main.audit, "record", rec)
    r = post(c, True)
    assert r.status_code == 200 and r.json()["ticket"]["id"] == "INC-1"


class TicketPool:
    """tickets table in memory: SELECT by thread, INSERT, UPDATE."""
    def __init__(self): self.rows = {}

    def connection(self):
        pool = self

        class C:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def rollback(s): pass

            def execute(s, q, args=()):
                class R:
                    def __init__(r, v): r.v = v
                    def fetchone(r): return r.v
                if q.startswith("SELECT id, created_at"):
                    return R(pool.rows.get(args[0]))
                if q.startswith("INSERT"):
                    import datetime
                    row = (len(pool.rows) + 1, datetime.datetime(2026, 1, 1), args[5], None)
                    pool.rows[args[0]] = row
                    return R(row[:2])
                return R(None)
        return C()


def test_create_ticket_is_idempotent_per_incident(monkeypatch):
    pool = TicketPool()
    monkeypatch.setattr(tools, "get_pool", lambda: pool)
    monkeypatch.setattr(tools, "deliver_ticket_webhook", lambda t: None)
    a = tools.create_ticket("t-1", {"cell_id": "C", "kpi": "k"}, "diag", "amira")
    b = tools.create_ticket("t-1", {"cell_id": "C", "kpi": "k"}, "diag", "someone-else")
    assert a["id"] == b["id"] == "INC-1" and len(pool.rows) == 1
    assert b["approved_by"] == "amira"              # the original approver is preserved
    assert tools.create_ticket("t-2", {"cell_id": "C", "kpi": "k"}, "d", "x")["id"] == "INC-2"
