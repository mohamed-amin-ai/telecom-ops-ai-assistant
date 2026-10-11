import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
from mcp import StdioServerParameters

from app import mcp_client

FAKE = StdioServerParameters(
    command=sys.executable, args=[str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")])


def test_real_server_exposes_only_read_tools():
    names = mcp_client.list_tools()
    assert names == ["get_kpis", "kpi_profile", "search_runbooks", "ticket_history"]
    assert "create_ticket" not in names


def test_call_returns_dict_and_list_results():
    assert mcp_client.call_tool("kpi_profile", {"cell_id": "c1", "kpi": "k"}, FAKE)["z"] == 3.2
    hits = mcp_client.call_tool("search_runbooks", {"query": "q"}, FAKE)
    assert hits == [{"source": "a.md", "chunk": 0, "text": "q"}]


def test_tool_error_raises():
    with pytest.raises(RuntimeError, match="boom"):
        mcp_client.call_tool("boom", {}, FAKE)


@pytest.mark.asyncio
async def test_works_from_inside_a_running_event_loop():
    assert mcp_client.call_tool("kpi_profile", {"cell_id": "c", "kpi": "k"}, FAKE)["cell_id"] == "c"


def test_agent_nodes_use_mcp_when_enabled(monkeypatch):
    from unittest.mock import MagicMock

    import app.db
    monkeypatch.setattr(app.db, "get_pool", lambda *a, **k: MagicMock())
    import dataclasses

    from app import agent
    monkeypatch.setattr(agent, "settings", dataclasses.replace(agent.settings, tools_via_mcp=True))
    seen = []
    monkeypatch.setattr(mcp_client, "call_tool",
                        lambda n, a, *x, **k: seen.append(n) or ({"z": 1} if n == "kpi_profile" else []))
    alert = {"cell_id": "c", "kpi": "k", "description": "d"}
    assert agent.kpi_node({"alert": alert}) == {"profile": {"z": 1}}
    assert agent.runbook_node({"alert": alert}) == {"runbook": []}
    assert seen == ["kpi_profile", "search_runbooks"]


def test_default_server_passes_environment_through():
    # Without this the spawned server loses DATABASE_URL/QDRANT_URL (found in CI).
    assert mcp_client.DEFAULT_SERVER.env is not None
    assert "PATH" in mcp_client.DEFAULT_SERVER.env


def test_session_is_reused_and_replaced_after_death():
    mcp_client.close_all()
    s = mcp_client._session(FAKE)
    mcp_client.call_tool("kpi_profile", {"cell_id": "a", "kpi": "k"}, FAKE)
    t1 = s._thread
    mcp_client.call_tool("kpi_profile", {"cell_id": "b", "kpi": "k"}, FAKE)
    assert s._thread is t1 and s.alive()          # one process for both calls
    s._loop.call_soon_threadsafe(s._stop.set)     # kill the transport under it
    t1.join(5)
    assert mcp_client.call_tool("kpi_profile", {"cell_id": "c", "kpi": "k"}, FAKE)["cell_id"] == "c"
    assert s._thread is not t1


def test_concurrent_callers_are_safe():
    from concurrent.futures import ThreadPoolExecutor
    mcp_client.close_all()
    with ThreadPoolExecutor(8) as ex:
        out = list(ex.map(lambda i: mcp_client.call_tool(
            "kpi_profile", {"cell_id": f"c{i}", "kpi": "k"}, FAKE)["cell_id"], range(24)))
    assert out == [f"c{i}" for i in range(24)]


def test_a_queued_call_timing_out_does_not_kill_the_running_call():
    """Regression: the wait for the shared pipe used to count against the caller's timeout and a
    timeout closed the whole session, killing the healthy call that was still running."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    mcp_client.close_all()
    mcp_client.call_tool("kpi_profile", {"cell_id": "w", "kpi": "k"}, FAKE)   # warm
    s = mcp_client._session(FAKE)
    gen = s._gen
    with ThreadPoolExecutor(2) as ex:
        a = ex.submit(mcp_client.call_tool, "slow", {"seconds": 3}, FAKE, 20)
        time.sleep(0.5)                                  # A now holds the pipe
        t0 = time.monotonic()
        b = ex.submit(mcp_client.call_tool, "kpi_profile", {"cell_id": "b", "kpi": "k"}, FAKE, 1)
        with pytest.raises(mcp_client.McpBusy):
            b.result()
        assert time.monotonic() - t0 < 4
        assert a.result() == {"slept": 3.0}              # A was not killed
    assert s._gen == gen and s.alive()                   # and the session was not replaced
    assert mcp_client.call_tool("kpi_profile", {"cell_id": "z", "kpi": "k"}, FAKE)["cell_id"] == "z"
    assert threading.active_count() < 50


def test_late_failure_does_not_close_a_newer_session():
    mcp_client.close_all()
    mcp_client.call_tool("kpi_profile", {"cell_id": "a", "kpi": "k"}, FAKE)
    s = mcp_client._session(FAKE)
    old_gen = s._gen
    s.close()
    mcp_client.call_tool("kpi_profile", {"cell_id": "b", "kpi": "k"}, FAKE)   # new generation
    assert s._gen == old_gen + 1
    s._close_if(old_gen)                                 # a straggler from the old generation
    assert s.alive()
