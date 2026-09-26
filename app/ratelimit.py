"""Sliding-window rate limiter. Uses Redis (correct across multiple API replicas) when
configured and reachable; falls back to an in-process window if Redis is unreachable, so
a Redis outage degrades rate limiting rather than taking the whole API down with it. The
in-process fallback is only correct for a single replica and resets on restart -- that
trade-off is deliberate: rate limiting is a guard, not a source of truth, so failing open
to "best effort per replica" beats failing closed and rejecting all traffic.
"""
import logging
import time
from collections import defaultdict, deque

import redis

from .config import settings

log = logging.getLogger("ratelimit")

_local_hits: dict[str, deque] = defaultdict(deque)
_redis: redis.Redis | None = None


def _get_redis() -> "redis.Redis | None":
    global _redis
    if not settings.redis_url:
        return None
    if _redis is None:
        _redis = redis.Redis.from_url(
            settings.redis_url, socket_timeout=0.2, socket_connect_timeout=0.2
        )
    return _redis


def _allow_local(key: str, limit: int, window: float) -> bool:
    now = time.monotonic()
    q = _local_hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def allow(key: str, limit: int, window: int = 60) -> bool:
    """True if a request from `key` is allowed under `limit` requests per `window` seconds."""
    r = _get_redis()
    if r is None:
        return _allow_local(key, limit, window)
    zkey = f"ratelimit:{key}"
    now = time.time()
    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(zkey, 0, now - window)
        pipe.zcard(zkey)
        pipe.zadd(zkey, {str(now): now})
        pipe.expire(zkey, window)
        _, count, _, _ = pipe.execute()
        if count >= limit:
            r.zrem(zkey, str(now))
            return False
        return True
    except redis.RedisError as e:
        log.warning("redis rate limiter unavailable (%s); falling back to in-process", e)
        return _allow_local(key, limit, window)
