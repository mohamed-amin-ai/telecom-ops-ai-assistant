"""Per-user API keys with roles, and client-IP resolution behind reverse proxies.

Keys are random high-entropy tokens stored as SHA-256 hashes (never in plaintext). Roles are
ordered: operator (ask, open incidents) < approver (also approve/reject) < admin (also read
the audit log). A revoked key stops working within CACHE_TTL seconds."""
import hashlib
import logging
import time
from dataclasses import dataclass

import psycopg
from fastapi import Header, HTTPException, Request

from . import metrics
from .config import settings
from .db import get_pool
from .ratelimit import allow

log = logging.getLogger("auth")

ROLE_RANK = {"operator": 1, "approver": 2, "admin": 3}
CACHE_TTL = 30.0


@dataclass(frozen=True)
class Principal:
    name: str
    role: str


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


_cache: dict[str, tuple[float, Principal]] = {}


def _lookup(key_hash: str) -> Principal | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT name, role FROM api_keys WHERE key_hash = %s AND revoked_at IS NULL",
            (key_hash,),
        ).fetchone()
    return Principal(row[0], row[1]) if row else None


def authenticate(key: str) -> Principal | None:
    h = hash_key(key)
    hit = _cache.get(h)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    p = _lookup(h)
    if p:
        _cache[h] = (time.monotonic(), p)
    else:
        _cache.pop(h, None)
    return p


def client_ip(request: Request) -> str:
    """The real client address. With N trusted proxies in front, each appends the peer it saw
    to X-Forwarded-For, so the client is the Nth entry from the right; anything a client put
    to the left of that is spoofable and ignored. With 0 trusted proxies the header is
    ignored entirely."""
    n = settings.trusted_proxies
    xff = request.headers.get("x-forwarded-for", "")
    if n > 0 and xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[max(0, len(parts) - n)]
    return request.client.host if request.client else "unknown"


def require(role: str):
    """FastAPI dependency: authenticate, enforce a minimum role, apply the per-user limit."""

    def dep(request: Request, x_api_key: str | None = Header(default=None)) -> Principal:
        if not settings.auth_required:
            p = Principal("anonymous", "admin")
        else:
            if not x_api_key:
                metrics.AUTH_FAILURES.labels("missing_key").inc()
                raise HTTPException(status_code=401, detail="missing API key")
            try:
                p = authenticate(x_api_key)
            except psycopg.Error as e:
                log.error("auth lookup failed: %s", e)
                raise HTTPException(status_code=503, detail="auth backend unavailable") from e
            if p is None:
                metrics.AUTH_FAILURES.labels("invalid_key").inc()
                raise HTTPException(status_code=401, detail="invalid API key")
        if ROLE_RANK[p.role] < ROLE_RANK[role]:
            metrics.AUTH_FAILURES.labels("forbidden").inc()
            raise HTTPException(status_code=403, detail=f"requires role '{role}' or higher")
        if settings.rate_limit_per_min > 0 and not allow(f"user:{p.name}", settings.rate_limit_per_min):
            metrics.RATE_LIMITED.labels("user").inc()
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        request.state.principal = p
        return p

    return dep
