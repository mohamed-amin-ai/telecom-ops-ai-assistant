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
