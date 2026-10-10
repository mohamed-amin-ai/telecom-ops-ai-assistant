from mcp.server.fastmcp import FastMCP

m = FastMCP("fake")


@m.tool()
def kpi_profile(cell_id: str, kpi: str) -> dict:
    return {"cell_id": cell_id, "kpi": kpi, "z": 3.2}


@m.tool()
def search_runbooks(query: str, k: int = 5) -> list[dict]:
    return [{"source": "a.md", "chunk": 0, "text": query}]


@m.tool()
def boom() -> dict:
    raise ValueError("nope")


if __name__ == "__main__":
    m.run()
