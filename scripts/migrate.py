"""Apply pending SQL migrations from db/migrations/, then set up LangGraph's own
checkpoint tables. Idempotent: safe to run on every deploy, and safe under concurrent
execution (e.g. two replicas starting at once) via an advisory lock.

Run:  python -m scripts.migrate
"""
import pathlib

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from app.config import settings

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "db" / "migrations"
LOCK_KEY = 872_364_501  # arbitrary constant, just needs to be consistent across runs


def applied(conn: psycopg.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    return {r[0] for r in conn.execute("SELECT filename FROM schema_migrations").fetchall()}


def main() -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"no migrations found in {MIGRATIONS_DIR}")
    with psycopg.connect(settings.database_url, autocommit=False) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        conn.commit()
        try:
            done = applied(conn)
            for f in files:
                if f.name in done:
                    print(f"skip  {f.name} (already applied)")
                    continue
                print(f"apply {f.name}")
                conn.execute(f.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,)
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            conn.commit()

    print("setting up LangGraph checkpoint tables")
    with PostgresSaver.from_conn_string(settings.database_url) as saver:
        saver.setup()
    print("migrations complete")


if __name__ == "__main__":
    main()
