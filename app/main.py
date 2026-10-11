import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

import psycopg
import redis as redis_lib
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from langgraph.types import Command
from pydantic import BaseModel, Field

from . import audit, metrics
from .agent import graph
from .auth import Principal, client_ip, require
from .config import settings
from .db import close_pool, get_pool
from .guardrails import check_input
from .observability import request_id_var, setup_logging, setup_sentry
from .rag import answer
from .ratelimit import allow
from .tracing import setup_tracing

setup_logging()
setup_sentry()
log = logging.getLogger("api")
OPERATOR = Depends(require("operator"))
APPROVER = Depends(require("approver"))
ADMIN = Depends(require("admin"))
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_tracing()  # no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set
    yield
    close_pool()  # release DB connections cleanly on SIGTERM instead of dropping them


app = FastAPI(title="Telecom Ops Assistant", root_path=settings.root_path, lifespan=lifespan)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type", "X-Request-ID"],
    )


@app.middleware("http")
async def observe(request: Request, call_next):
    """Request id, coarse per-IP limit, metrics and one structured log line per request."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    token = request_id_var.set(rid)
    start = time.perf_counter()
    ip = client_ip(request)
    try:
        limited = request.url.path.startswith(("/ask", "/incident"))
        if limited and settings.ip_rate_limit_per_min > 0 and not allow(
            f"ip:{ip}", settings.ip_rate_limit_per_min
        ):
            metrics.RATE_LIMITED.labels("ip").inc()
            response = JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        else:
            response = await call_next(request)
    except Exception as e:  # last-resort handler: log, report, return JSON
        log.exception("unhandled error")
        if settings.sentry_dsn:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        response = JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500)
    elapsed = time.perf_counter() - start
    route = getattr(request.scope.get("route"), "path", "unmatched")
    metrics.HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    metrics.HTTP_LATENCY.labels(route).observe(elapsed)
    response.headers["X-Request-ID"] = rid
    p = getattr(request.state, "principal", None)
    log.info("request", extra={"fields": {
        "method": request.method, "path": request.url.path, "status": response.status_code,
        "ms": round(elapsed * 1000, 1), "ip": ip, "user": p.name if p else None,
    }})
    request_id_var.reset(token)
    return response


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class Alert(BaseModel):
    cell_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    kpi: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    description: str = Field(default="", max_length=500)


class Decision(BaseModel):
    approve: bool


def _shape(tid: str, out: dict) -> dict:
    return {
        "thread_id": tid,
        "status": "awaiting_approval" if out.get("__interrupt__") else "done",
        "profile": out.get("profile"),
        "investigation": [{"tool": t.get("tool"), "outcome": t.get("outcome")}
                          for t in out.get("trace") or []],  # which tools ran, not their data
        "diagnosis": out.get("diagnosis"),
        "ticket": out.get("ticket"),
        "report": out.get("report"),
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/ready")
def ready():
    """Readiness for load balancers: the database is required; Redis only degrades rate limiting."""
    try:
        with get_pool().connection() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as e:
        raise HTTPException(status_code=503, detail="database unavailable") from e
    redis_ok = True
    if settings.redis_url:
        try:
            redis_lib.Redis.from_url(settings.redis_url, socket_timeout=0.5).ping()
        except redis_lib.RedisError:
            redis_ok = False
    return {"ok": True, "redis": redis_ok}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    body, ctype = metrics.render()
    return Response(body + metrics.kpi_freshness_lines(), media_type=ctype)


@app.get("/whoami")
def whoami(p: Principal = OPERATOR):
    return {"name": p.name, "role": p.role}


@app.post("/ask")
def ask(b: Ask, p: Principal = OPERATOR):
    return answer(b.question)


@app.post("/incident")
def open_incident(a: Alert, p: Principal = OPERATOR):
    alert = a.model_dump()
    if settings.guardrails_enabled and a.description:
        v = check_input(a.description, kind="alert")
        if not v.allowed:
            raise HTTPException(status_code=400, detail=f"alert description rejected: {v.label}")
        alert["description"] = v.text
    tid = str(uuid.uuid4())
    audit.record(p.name, "incident_opened", tid, cell_id=a.cell_id, kpi=a.kpi)
    out = graph.invoke({"alert": alert}, {"configurable": {"thread_id": tid}})
    return _shape(tid, out)


@app.post("/incident/{tid}/decision")
def decide(tid: str, d: Decision, p: Principal = APPROVER):
    if not UUID_RE.match(tid):
        raise HTTPException(status_code=404, detail="unknown incident")
    cfg = {"configurable": {"thread_id": tid}}
    snap = graph.get_state(cfg)
    if not snap.values:
        raise HTTPException(status_code=404, detail="unknown incident")
    if not snap.next:
        raise HTTPException(status_code=409, detail="incident already decided")
    # One decision at a time per incident: a second concurrent approver gets 409 instead of
    # racing the first into creating a duplicate ticket.
    with get_pool().connection() as lock_conn:
        got = lock_conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (tid,)).fetchone()[0]
        if not got:
            raise HTTPException(status_code=409, detail="a decision is already in progress")
        try:
            if not graph.get_state(cfg).next:
                raise HTTPException(status_code=409, detail="incident already decided")
            pending = graph.get_state(cfg).next
            if "approval" in pending:
                audit.record(p.name, "decision", tid, approve=d.approve)  # fail-closed
                resume = Command(resume={"approve": d.approve, "by": p.name})
            else:
                # The decision was already taken and a later step (ticket / report) failed, so
                # the checkpoint is waiting on it. A retry may only continue that decision: it
                # cannot flip it (a "reject" here must not be able to create a ticket, and an
                # "approve" must not resurrect a rejection -- hence the 409s below).
                state = graph.get_state(cfg).values
                if d.approve != bool(state.get("approved")):
                    raise HTTPException(status_code=409, detail=(
                        "incident was already " + ("approved" if state.get("approved")
                                                   else "rejected") + "; only a retry of the "
                        "same decision is accepted"))
                audit.record(p.name, "decision_retry", tid, approve=d.approve)
                resume = None
            with get_pool().connection() as wait_conn:
                opened = wait_conn.execute(
                    "SELECT EXTRACT(EPOCH FROM (now() - ts)) FROM audit_log "
                    "WHERE thread_id = %s AND action = 'incident_opened' ORDER BY id LIMIT 1",
                    (tid,)).fetchone()
            if opened and opened[0] is not None and resume is not None:
                metrics.APPROVAL_WAIT.observe(float(opened[0]))
            out = graph.invoke(resume, cfg)
            if resume is not None:
                metrics.APPROVALS.labels("approved" if d.approve else "rejected").inc()
            if out.get("ticket"):
                try:
                    audit.record(p.name, "ticket_created", tid, ticket_id=out["ticket"]["id"])
                except psycopg.Error:  # the ticket exists; never turn that into a 500
                    log.exception("audit write for ticket_created failed (ticket %s)",
                                  out["ticket"]["id"])
            return _shape(tid, out)
        finally:
            lock_conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (tid,))


@app.get("/audit")
def audit_trail(thread_id: str | None = None, limit: int = Query(100, ge=1, le=500),
                p: Principal = ADMIN):
    return {"entries": audit.recent(thread_id, limit)}
