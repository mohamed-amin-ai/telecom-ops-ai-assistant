import asyncio
import importlib.util
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "load_test", Path(__file__).resolve().parent.parent / "scripts" / "load_test.py")
lt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lt)


def test_open_loop_keeps_arrival_rate_when_server_is_slow(monkeypatch):
    """Each fake request takes 0.5s but arrivals are 20/s: a closed loop with concurrency 1
    would finish 10 requests in ~5s; open loop must finish them in ~0.5s + 0.5s."""
    async def fake(client, url, i):
        await asyncio.sleep(0.5)
        return 0.5, (429 if i % 5 == 0 else 200)
    monkeypatch.setattr(lt, "one_request", fake)
    t = time.perf_counter()
    r = asyncio.run(lt.run_open_loop("http://x", rps=20, duration=0.5))
    assert time.perf_counter() - t < 2.0
    assert r["total"] == 10 and r["rate_limited_429"] == 2 and r["failed"] == 0
    assert r["ok"] == 8 and r["p50_s"] == 0.5


def test_connection_errors_count_as_failures(monkeypatch):
    async def fake(client, url, i):
        return 0.1, 0
    monkeypatch.setattr(lt, "one_request", fake)
    r = asyncio.run(lt.run_open_loop("http://x", rps=10, duration=0.5))
    assert r["failed"] == 5 and r["failure_rate"] == 1.0
