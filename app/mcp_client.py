"""Call the read-only MCP server (app/mcp_server.py) over stdio.

Enabled with TOOLS_VIA_MCP=1. The server is spawned per call: simple and isolated, at the
cost of process-start latency on every tool call, so it is off by default. Write actions
(create_ticket) are never exposed over MCP; they stay behind the agent's approval gate."""
import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# The SDK launches the server with a minimal environment (PATH, HOME, ...) unless told
# otherwise, which drops DATABASE_URL/QDRANT_URL and breaks every tool. Pass ours through.
DEFAULT_SERVER = StdioServerParameters(
    command=sys.executable, args=["-m", "app.mcp_server"], env=dict(os.environ))


async def _call(server: StdioServerParameters, name: str, args: dict, timeout: float):
    # Never raise inside the stdio/session context managers: anyio wraps it in an
    # ExceptionGroup and tears the transport down noisily. Capture, exit cleanly, then raise.
    async with stdio_client(server) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        res = await asyncio.wait_for(session.call_tool(name, args), timeout)
    if res.isError:
        raise RuntimeError(f"MCP tool {name} failed: "
                           f"{' '.join(getattr(c, 'text', '') for c in res.content)}")
    if res.structuredContent is not None:
        sc = res.structuredContent
        # FastMCP wraps non-object results (lists) as {"result": [...]}
        return sc["result"] if set(sc) == {"result"} else sc
    return json.loads(res.content[0].text)


async def _list(server: StdioServerParameters) -> list[str]:
    async with stdio_client(server) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        return sorted(t.name for t in (await session.list_tools()).tools)


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(1) as ex:  # called from inside a running loop
        return ex.submit(asyncio.run, coro).result()


def call_tool(name: str, args: dict, server: StdioServerParameters = DEFAULT_SERVER,
              timeout: float = 60.0):
    return _run(_call(server, name, args, timeout))


def list_tools(server: StdioServerParameters = DEFAULT_SERVER) -> list[str]:
    return _run(_list(server))
