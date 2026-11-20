"""Warm the weather and search servers' outbound connections (TLS to Open-Meteo / Tavily) with one cheap call each,
so the first real tool call in a demo is not slowed by a cold connect. Safe to fail. Costs 1 Tavily credit."""
import asyncio
import time

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def call(url, tool, args):
    async with streamable_http_client(url) as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            t = time.monotonic()
            await s.call_tool(tool, args)
            return time.monotonic() - t


async def main():
    for url, tool, args in [("http://127.0.0.1:8103/mcp", "get_weather", {"city": "Manila"}),
                            ("http://127.0.0.1:8104/mcp", "web_search", {"query": "today"})]:
        try:
            print(f"warmed {tool} in {await call(url, tool, args):.2f}s")
        except Exception as e:
            print(f"warm {tool} failed: {type(e).__name__}")

asyncio.run(main())
