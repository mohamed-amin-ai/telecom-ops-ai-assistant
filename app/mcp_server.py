"""MCP server exposing READ-ONLY tools. create_ticket is deliberately not exposed:
write actions go through the agent's approval gate."""
from mcp.server.fastmcp import FastMCP

from . import tools
from .rag import retrieve

mcp = FastMCP("telecom-ops")


@mcp.tool()
def get_kpis(cell_id: str, kpi: str, hours: int = 24) -> list[dict]:
    """Fetch a KPI time series for a cell over the last N hours."""
    return tools.get_kpis(cell_id, kpi, hours)


@mcp.tool()
def kpi_profile(cell_id: str, kpi: str) -> dict:
    """Compare the last 4 hours of a KPI with its same-hour baseline (z-score)."""
    return tools.kpi_profile(cell_id, kpi)


@mcp.tool()
def search_runbooks(query: str, k: int = 5) -> list[dict]:
    """Hybrid search over runbooks and telecom docs."""
    return retrieve(query, k=k)


if __name__ == "__main__":
    mcp.run()
