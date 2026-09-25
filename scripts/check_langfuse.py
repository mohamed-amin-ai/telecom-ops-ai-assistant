"""Fail unless Langfuse received at least one trace (proves LiteLLM -> Langfuse tracing).
Env: LANGFUSE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY."""
import base64
import json
import os
import sys
import time
import urllib.request

host = os.getenv("LANGFUSE_URL", "http://localhost:3000")
auth = base64.b64encode(
    f"{os.getenv('LANGFUSE_PUBLIC_KEY', 'pk-lf-ci')}:{os.getenv('LANGFUSE_SECRET_KEY', 'sk-lf-ci')}".encode()
).decode()
last = None
for _ in range(30):
    try:
        req = urllib.request.Request(f"{host}/api/public/traces?limit=10",
                                     headers={"Authorization": f"Basic {auth}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r).get("data", [])
        if data:
            print(f"OK: {len(data)} trace(s), e.g. {[t.get('name') for t in data[:3]]}")
            sys.exit(0)
        last = "no traces yet"
    except Exception as e:  # noqa: BLE001
        last = repr(e)
    time.sleep(5)
print("FAIL: no Langfuse traces received:", last)
sys.exit(1)
