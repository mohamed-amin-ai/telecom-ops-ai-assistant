"""Concurrency smoke test: fires N concurrent requests at /ask and reports latency
percentiles and the error rate. Not a substitute for real load testing (k6, Locust) against
production-like traffic and infrastructure -- this just catches "it falls over under any
concurrency at all" before that ships, and gives a real number instead of none.

Run:  python scripts/load_test.py [--concurrency 20] [--total 100] [--url http://localhost:8000]
"""
import argparse
import asyncio
import os
import sys
import time

import httpx

API_KEY = os.getenv("API_KEY", "")

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
        headers = {"X-API-Key": API_KEY} if API_KEY else {}
        r = await client.post(f"{url}/ask", json={"question": QUESTIONS[i % len(QUESTIONS)]},
                              headers=headers, timeout=60)
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


async def run_open_loop(url: str, rps: float, duration: float) -> dict:
    """Open-loop soak: start a request every 1/rps seconds regardless of how slow earlier ones
    are. A closed loop (above) slows its own arrivals when the server slows down and so hides
    queueing ("coordinated omission"); this one does not. Errors split into 429 (our own rate
    limit answering correctly) and real failures (5xx / timeouts / connection errors)."""
    n = int(rps * duration)
    start = time.perf_counter()
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=1000)) as client:
        tasks = []
        for i in range(n):
            delay = start + i / rps - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(one_request(client, url, i)))
        results = await asyncio.gather(*tasks)
    lat = sorted(r[0] for r in results)
    codes = [r[1] for r in results]

    def pct(p: float) -> float:
        return round(lat[min(len(lat) - 1, int(len(lat) * p))], 3)

    return {
        "mode": "open-loop", "rps": rps, "duration_s": duration, "total": n,
        "ok": codes.count(200), "rate_limited_429": codes.count(429),
        "failed": sum(1 for c in codes if c not in (200, 429)),
        "failure_rate": round(sum(1 for c in codes if c not in (200, 429)) / max(n, 1), 3),
        "p50_s": pct(0.5), "p95_s": pct(0.95), "p99_s": pct(0.99), "max_s": round(lat[-1], 3),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--total", type=int, default=100)
    ap.add_argument("--rps", type=float, default=0, help="open-loop soak: requests/second")
    ap.add_argument("--duration", type=float, default=60, help="open-loop soak seconds")
    ap.add_argument("--max-error-rate", type=float, default=0.05)
    ap.add_argument("--max-p95-s", type=float, default=30.0)
    a = ap.parse_args()

    import json
    if a.rps:
        result = asyncio.run(run_open_loop(a.url, a.rps, a.duration))
        print(json.dumps(result))
        if result["failure_rate"] > a.max_error_rate or result["p95_s"] > a.max_p95_s:
            print("BELOW FLOOR")
            sys.exit(1)
        sys.exit(0)
    result = asyncio.run(run(a.url, a.concurrency, a.total))
    print(json.dumps(result))

    if result["error_rate"] > a.max_error_rate:
        print(f"BELOW FLOOR: error_rate {result['error_rate']} > {a.max_error_rate}")
        sys.exit(1)
    if result["p95_s"] > a.max_p95_s:
        print(f"BELOW FLOOR: p95 {result['p95_s']}s > {a.max_p95_s}s")
        sys.exit(1)
