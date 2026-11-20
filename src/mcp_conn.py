"""A long-lived MCP client connection (streamable HTTP) owned by one background task.

The MCP SDK uses anyio task groups, which must be entered and exited from the same task. Pipecat processors set up
and clean up in different tasks, so the session lives in its own owner task and everyone else just calls call().
"""
import asyncio

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


class McpConn:
    def __init__(self, url: str):
        self.url = url
        self.session: ClientSession | None = None
        self._task: asyncio.Task | None = None
        self._closing = asyncio.Event()

    async def start(self):
        if self._task is not None and not self._task.done():
            return
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self._closing.clear()
        self._task = asyncio.create_task(self._run(ready))
        await ready

    async def _run(self, ready: asyncio.Future):
        try:
            async with streamable_http_client(self.url) as st:
                async with ClientSession(st[0], st[1]) as s:
                    await s.initialize()
                    self.session = s
                    ready.set_result(True)
                    await self._closing.wait()
        except Exception as e:
            if not ready.done():
                ready.set_exception(e)
        finally:
            self.session = None

    async def call(self, tool: str, args: dict | None = None) -> str:
        if self.session is None:
            await self.start()
        r = await self.session.call_tool(tool, args or {})
        if r.is_error:
            raise RuntimeError(f"{tool} failed: {r.content}")
        return r.content[0].text if r.content else ""

    async def close(self):
        self._closing.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=3)
            except Exception:
                self._task.cancel()
