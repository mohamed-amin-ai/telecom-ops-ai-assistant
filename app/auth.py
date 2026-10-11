"""Per-user API keys with roles, and client-IP resolution behind reverse proxies.

Keys are random high-entropy tokens stored as SHA-256 hashes (never in plaintext). Roles are
ordered: operator (ask, open incidents) < approver (also approve/reject) < admin (also read
the audit log). A revoked key stops working within CACHE_TTL seconds."""
import hashlib
import json
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


_jwk_client = None


def _signing_key(token: str):
    """The public key that signed `token`: static JWKS if configured, else fetched (and cached
    by PyJWT) from OIDC_JWKS_URL."""
    global _jwk_client
    import jwt

    if settings.oidc_jwks_json:
        keys = jwt.PyJWKSet.from_dict(json.loads(settings.oidc_jwks_json)).keys
        kid = jwt.get_unverified_header(token).get("kid")
        for k in keys:
            if kid is None or k.key_id == kid:
                return k.key
        raise jwt.InvalidKeyError("no matching signing key")
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(settings.oidc_jwks_url, cache_keys=True, lifespan=3600)
    return _jwk_client.get_signing_key_from_jwt(token).key


def _claim(claims: dict, dotted: str):
    cur = claims
    for part in dotted.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def authenticate_bearer(token: str) -> Principal | None:
    """Verify an OIDC access token (signature, expiry, issuer, audience; asymmetric algorithms
    only) and map its role claim to the highest of operator/approver/admin. None if invalid or
    if it carries no recognised role."""
    import jwt

    try:
        claims = jwt.decode(
            token, _signing_key(token), algorithms=["RS256", "RS384", "RS512", "ES256", "ES384"],
            audience=settings.oidc_audience, issuer=settings.oidc_issuer,
            options={"require": ["exp", "iss", "aud"]})
    except (jwt.PyJWTError, ValueError, KeyError) as e:
        log.info("bearer token rejected: %s", type(e).__name__)
        return None
    raw = _claim(claims, settings.oidc_role_claim) or []
    if isinstance(raw, str):
        roles = [raw]
    elif isinstance(raw, (list, tuple)):
        roles = [r for r in raw if isinstance(r, str)]
    else:
        roles = []
    best = max((r for r in roles if r in ROLE_RANK), key=ROLE_RANK.get, default=None)
    name = str(claims.get(settings.oidc_name_claim) or claims.get("email") or claims["sub"])
    # Namespaced so an SSO user can never share a rate-limit bucket or audit identity with an
    # API-key principal of the same name.
    return Principal(f"sso:{name}", best) if best else None


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

    def dep(request: Request, x_api_key: str | None = Header(default=None),
            authorization: str | None = Header(default=None)) -> Principal:
        bearer = (authorization[7:].strip() if authorization
                  and authorization[:7].lower() == "bearer " else "")
        if not settings.auth_required:
            p = Principal("anonymous", "admin")
        elif bearer and settings.oidc_issuer and not x_api_key:
            p = authenticate_bearer(bearer)
            if p is None:
                metrics.AUTH_FAILURES.labels("invalid_token").inc()
                raise HTTPException(status_code=401, detail="invalid or unauthorised token")
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
