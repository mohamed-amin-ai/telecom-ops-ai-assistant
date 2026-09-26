import hmac
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from .agent import graph
from .config import settings
from .guardrails import check_input
from .rag import answer
from .ratelimit import allow

app = FastAPI(title="Telecom Ops Assistant")


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Per-client sliding window on the LLM-backed routes (Redis-backed; see ratelimit.py)."""
    limit = settings.rate_limit_per_min
    if limit > 0 and request.url.path.startswith(("/ask", "/incident")):
        ip = request.client.host if request.client else "unknown"
        if not allow(ip, limit):
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
    return await call_next(request)


def auth(x_api_key: str | None = Header(default=None)) -> None:
    """Optional shared-secret auth: enabled when API_KEY is set."""
    if settings.api_key and not hmac.compare_digest(x_api_key or "", settings.api_key):
        raise HTTPException(status_code=401, detail="invalid API key")


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
        "diagnosis": out.get("diagnosis"),
        "ticket": out.get("ticket"),
        "report": out.get("report"),
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/ask", dependencies=[Depends(auth)])
def ask(b: Ask):
    return answer(b.question)


@app.post("/incident", dependencies=[Depends(auth)])
def open_incident(a: Alert):
    alert = a.model_dump()
    if settings.guardrails_enabled and a.description:
        v = check_input(a.description, kind="alert")
        if not v.allowed:
            raise HTTPException(status_code=400, detail=f"alert description rejected: {v.label}")
        alert["description"] = v.text
    tid = str(uuid.uuid4())
    out = graph.invoke({"alert": alert}, {"configurable": {"thread_id": tid}})
    return _shape(tid, out)


@app.post("/incident/{tid}/decision", dependencies=[Depends(auth)])
def decide(tid: str, d: Decision):
    out = graph.invoke(Command(resume=d.approve), {"configurable": {"thread_id": tid}})
    return _shape(tid, out)
