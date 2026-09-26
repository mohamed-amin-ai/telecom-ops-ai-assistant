"""Concurrency smoke test: fires N concurrent requests at /ask and reports latency
percentiles and the error rate. Not a substitute for real load testing (k6, Locust) against
production-like traffic and infrastructure -- this just catches "it falls over under any
concurrency at all" before that ships, and gives a real number instead of none.

Run:  python scripts/load_test.py [--concurrency 20] [--total 100] [--url http://localhost:8000]
"""
import argparse
import asyncio
import sys
import time

import httpx

QUESTIONS = [
    "What is the ping-pong handover threshold?",
    "What should I check when a cell has PRB utilization above 85%?",
    "What is the cell availability target?",
    "When does an RRC setup failure become P2?",
    "What backhaul packet loss triggers an alert?",
]


async def one_request(client: httpx.AsyncClient, url: str, i: int) -> tuple[float, int]:
    t0 = time.perf_counter()
    try:
        r = await client.post(f"{url}/ask", json={"question": QUESTIONS[i % len(QUESTIONS)]},
                              timeout=60)
        return time.perf_counter() - t0, r.status_code
    except httpx.HTTPError:
        return time.perf_counter() - t0, 0


async def run(url: str, concurrency: int, total: int) -> dict:
    sem = asyncio.Semaphore(concurrency)

    async def bound(client, i):
        async with sem:
            return await one_request(client, url, i)

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(bound(client, i) for i in range(total)))

    latencies = [r[0] for r in results]
    codes = [r[1] for r in results]
    errors = sum(1 for c in codes if c != 200)
    latencies.sort()

    def pct(p: float) -> float:
        idx = min(len(latencies) - 1, int(len(latencies) * p))
        return round(latencies[idx], 3)

    return {
        "total": total, "concurrency": concurrency, "errors": errors,
        "error_rate": round(errors / total, 3),
        "p50_s": pct(0.50), "p95_s": pct(0.95), "p99_s": pct(0.99),
        "max_s": round(max(latencies), 3),
        "status_codes": sorted(set(codes)),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--total", type=int, default=100)
    ap.add_argument("--max-error-rate", type=float, default=0.05)
    ap.add_argument("--max-p95-s", type=float, default=30.0)
    a = ap.parse_args()

    result = asyncio.run(run(a.url, a.concurrency, a.total))
    import json
    print(json.dumps(result))

    if result["error_rate"] > a.max_error_rate:
        print(f"BELOW FLOOR: error_rate {result['error_rate']} > {a.max_error_rate}")
        sys.exit(1)
    if result["p95_s"] > a.max_p95_s:
        print(f"BELOW FLOOR: p95 {result['p95_s']}s > {a.max_p95_s}s")
        sys.exit(1)
