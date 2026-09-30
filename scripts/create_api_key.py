"""Create or revoke per-user API keys.

  python -m scripts.create_api_key --name alice --role approver     # prints the key ONCE
  python -m scripts.create_api_key --revoke alice                   # revokes all of alice's keys
  python -m scripts.create_api_key --list

Only the SHA-256 hash is stored; a lost key can't be recovered, only replaced."""
import argparse
import secrets

from app.auth import ROLE_RANK, hash_key
from app.db import get_pool


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name")
    ap.add_argument("--role", choices=sorted(ROLE_RANK), default="operator")
    ap.add_argument("--revoke", metavar="NAME")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    pool = get_pool()
    with pool.connection() as conn:
        if a.list:
            for r in conn.execute(
                "SELECT name, role, created_at, revoked_at FROM api_keys ORDER BY id"
            ).fetchall():
                print(f"{r[0]:20} {r[1]:9} created={r[2]:%Y-%m-%d} "
                      f"{'REVOKED' if r[3] else 'active'}")
        elif a.revoke:
            n = conn.execute(
                "UPDATE api_keys SET revoked_at = now() WHERE name = %s AND revoked_at IS NULL",
                (a.revoke,),
            ).rowcount
            print(f"revoked {n} key(s) for {a.revoke} (effective within 30s)")
        elif a.name:
            key = secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO api_keys (name, role, key_hash) VALUES (%s, %s, %s)",
                (a.name, a.role, hash_key(key)),
            )
            print(f"name={a.name} role={a.role}\nAPI key (shown once): {key}")
        else:
            ap.error("give --name, --revoke or --list")


if __name__ == "__main__":
    main()
