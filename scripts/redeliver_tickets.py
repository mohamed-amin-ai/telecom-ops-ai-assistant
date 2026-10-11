"""Retry ITSM hand-off for tickets whose webhook delivery failed (dead-letter sweep).

  python -m scripts.redeliver_tickets [--limit 50]

Exit code 1 if any ticket is still failing, so a CronJob/alert can notice."""
import argparse
import json
import sys

from app.tools import redeliver_failed

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    res = redeliver_failed(ap.parse_args().limit)
    print(json.dumps(res))
    sys.exit(1 if res.get("failed") else 0)
