"""Shared Postgres connection pool. One pool per process, created lazily so importing
this module never opens a connection by itself (kept out of the plain `pytest -q` path,
which runs with no database available)."""
from functools import lru_cache

from psycopg_pool import ConnectionPool

from .config import settings


@lru_cache
def get_pool() -> ConnectionPool:
    return ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=settings.db_pool_max,
        timeout=10,  # fail a request fast instead of queueing forever if the pool is exhausted
        kwargs={"autocommit": True},
    )


def close_pool() -> None:
    if get_pool.cache_info().currsize:
        get_pool().close()
        get_pool.cache_clear()
