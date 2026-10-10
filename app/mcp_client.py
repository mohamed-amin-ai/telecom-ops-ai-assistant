"""Call the read-only MCP server (app/mcp_server.py) over stdio.

One long-lived server process per API worker, started on first use and reused for every tool
call (starting a Python process per call cost far more than the tool itself). The connection
is owned by a background thread with its own event loop, so it works from sync code, from
FastAPI worker threads and from inside a running loop. Calls are serialised on one pipe; if
the transport dies the session is replaced and the call retried once. Write actions
(create_ticket) are never exposed over MCP; they stay behind the agent's approval gate."""
import asyncio
import atexit
import json
import os
import sys
import threading

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# The SDK launches the server with a minimal environment (PATH, HOME, ...) unless told
# otherwise, which drops DATABASE_URL/QDRANT_URL and breaks every tool. Pass ours through.
DEFAULT_SERVER = StdioServerParameters(
    command=sys.executable, args=["-m", "app.mcp_server"], env=dict(os.environ))


def _parse(name: str, res):
    if res.isError:
        raise RuntimeError(f"MCP tool {name} failed: "
                           f"{' '.join(getattr(c, 'text', '') for c in res.content)}")
    if res.structuredContent is not None:
        sc = res.structuredContent
        # FastMCP wraps non-object results (lists) as {"result": [...]}
        return sc["result"] if set(sc) == {"result"} else sc
    return json.loads(res.content[0].text)


class Session:
    def __init__(self, server: StdioServerParameters):
        self.server = server
        self._guard = threading.Lock()
        self._loop = None
        self._thread = None
        self._session = None
        self._stop = None
        self._alock = None

    async def _hold(self, ready: threading.Event, failed: list):
        # Never raise inside the stdio/session context managers: anyio would wrap it in an
        # ExceptionGroup and tear the transport down noisily. Capture, exit, report.
        try:
            async with stdio_client(self.server) as (r, w), ClientSession(r, w) as session:
                await session.initialize()
                self._session, self._stop, self._alock = session, asyncio.Event(), asyncio.Lock()
                ready.set()
                await self._stop.wait()
        except BaseException as e:  # noqa: BLE001 -- startup failure or teardown noise
            failed.append(e)
        finally:
            self._session = None
            ready.set()

    def _start(self):
        ready, failed = threading.Event(), []
        loop = self._loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._hold(ready, failed))

        self._thread = threading.Thread(target=run, daemon=True, name="mcp-session")
        self._thread.start()
        if not ready.wait(30) or self._session is None:
            raise RuntimeError(f"MCP server did not start: {failed[:1]}")

    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._session is not None)

    def close(self):
        with self._guard:
            self._close_locked()

    def _close_locked(self):
        if self._thread and self._thread.is_alive() and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
            self._thread.join(5)
        self._thread = self._session = None

    async def _do(self, op: str, name: str, args: dict, timeout: float):
        async with self._alock:
            if op == "list":
                return await asyncio.wait_for(self._session.list_tools(), timeout)
            return await asyncio.wait_for(self._session.call_tool(name, args), timeout)

    def request(self, op: str, name: str = "", args: dict | None = None, timeout: float = 60.0):
        last = None
        for _ in range(2):  # second attempt runs on a fresh server process
            with self._guard:
                if not self.alive():
                    self._close_locked()
                    self._start()
                loop = self._loop
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._do(op, name, args or {}, timeout), loop)
                return fut.result(timeout + 5)
            except TimeoutError:
                self.close()
                raise
            except Exception as e:  # noqa: BLE001 -- broken pipe, dead server, protocol error
                last = e
                self.close()
        raise RuntimeError(f"MCP transport failed twice: {last!r}")


_sessions: dict[tuple, Session] = {}
_sessions_lock = threading.Lock()


def _session(server: StdioServerParameters) -> Session:
    key = (server.command, tuple(server.args))
    with _sessions_lock:
        return _sessions.setdefault(key, Session(server))


def close_all():
    with _sessions_lock:
        for s in _sessions.values():
            s.close()
        _sessions.clear()


atexit.register(close_all)


def call_tool(name: str, args: dict, server: StdioServerParameters = DEFAULT_SERVER,
              timeout: float = 60.0):
    return _parse(name, _session(server).request("call", name, args, timeout))


def list_tools(server: StdioServerParameters = DEFAULT_SERVER) -> list[str]:
    return sorted(t.name for t in _session(server).request("list").tools)
