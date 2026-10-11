import dataclasses

import httpx
import pytest

from app import tools

TICKET = {"id": "INC-7", "thread_id": "t", "approved_by": "amira",
          "alert": {"cell_id": "CELL_001", "kpi": "prb_utilization_pct"},
          "diagnosis": "PRB saturation. Severity: P2 (peak hours)", "created_at": "x"}


def cfg(monkeypatch, **kw):
    monkeypatch.setattr(tools, "settings", dataclasses.replace(
        tools.settings, ticket_webhook_url="https://itsm.example/issue", **kw))
    monkeypatch.setattr(tools.time, "sleep", lambda s: None)


def capture(monkeypatch, codes):
    seen = []

    def post(url, content, headers, timeout):
        seen.append((url, content, headers))
        code = codes[min(len(seen) - 1, len(codes) - 1)]
        if isinstance(code, Exception):
            raise code
        return httpx.Response(code)
    monkeypatch.setattr(tools.httpx, "post", post)
    return seen


def test_jira_payload_shape_and_auth(monkeypatch):
    cfg(monkeypatch, ticket_webhook_format="jira", jira_project_key="OPS",
        ticket_webhook_auth="Basic abc")
    seen = capture(monkeypatch, [201])
    assert tools.deliver_ticket_webhook(TICKET) == "delivered"
    import json
    body = json.loads(seen[0][1])["fields"]
    assert body["project"] == {"key": "OPS"} and body["issuetype"] == {"name": "Incident"}
    assert "INC-7" in body["labels"] and "CELL_001" in body["summary"]
    assert "amira" in body["description"] and "Severity: P2" in body["description"]
    h = seen[0][2]
    assert h["Authorization"] == "Basic abc" and h["Idempotency-Key"] == "INC-7"


def test_generic_payload_is_the_ticket_and_signed(monkeypatch):
    cfg(monkeypatch, ticket_webhook_secret="s3cret")
    seen = capture(monkeypatch, [200])
    assert tools.deliver_ticket_webhook(TICKET) == "delivered"
    assert seen[0][2]["X-Signature-256"].startswith("sha256=")


def test_retries_5xx_and_429_but_not_4xx(monkeypatch):
    cfg(monkeypatch)
    seen = capture(monkeypatch, [503, 429, 200])
    assert tools.deliver_ticket_webhook(TICKET) == "delivered" and len(seen) == 3
    seen = capture(monkeypatch, [400])
    assert tools.deliver_ticket_webhook(TICKET) == "failed:400" and len(seen) == 1
    seen = capture(monkeypatch, [httpx.ConnectError("x")])
    assert tools.deliver_ticket_webhook(TICKET).startswith("failed:ConnectError")
    assert len(seen) == 3


def test_no_webhook_means_none(monkeypatch):
    monkeypatch.setattr(tools, "settings", dataclasses.replace(tools.settings,
                                                               ticket_webhook_url=""))
    assert tools.deliver_ticket_webhook(TICKET) is None


class FakePool:
    """Just enough of the pool API for redeliver_failed."""
    def __init__(self, failed_ids):
        self.failed, self.updates = failed_ids, []

    def connection(self):
        pool = self

        class Conn:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def execute(s, q, args=()):
                class R:
                    def fetchall(r): return [(i,) for i in pool.failed]
                if q.startswith("UPDATE"):
                    pool.updates.append(args)
                return R()
        return Conn()


@pytest.mark.parametrize("outcomes,delivered,failed", [(["delivered", "failed:503"], 1, 1)])
def test_redeliver_failed_updates_status_per_ticket(monkeypatch, outcomes, delivered, failed):
    cfg(monkeypatch)
    pool = FakePool([1, 2])
    monkeypatch.setattr(tools, "get_pool", lambda: pool)
    monkeypatch.setattr(tools, "get_ticket", lambda tid: {**TICKET, "id": tid})
    it = iter(outcomes)
    monkeypatch.setattr(tools, "deliver_ticket_webhook", lambda t: next(it))
    res = tools.redeliver_failed()
    assert res == {"retried": 2, "delivered": delivered, "failed": failed}
    assert pool.updates == [("delivered", 1), ("failed:503", 2)]


def test_redeliver_without_webhook_is_a_noop(monkeypatch):
    monkeypatch.setattr(tools, "settings", dataclasses.replace(tools.settings,
                                                               ticket_webhook_url=""))
    pool = FakePool([1])
    monkeypatch.setattr(tools, "get_pool", lambda: pool)
    monkeypatch.setattr(tools, "get_ticket", lambda tid: dict(TICKET))
    assert tools.redeliver_failed()["note"] == "no webhook configured"
    assert pool.updates == []
