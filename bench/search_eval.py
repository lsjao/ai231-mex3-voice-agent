"""Answer-key-free search health check: runs a varied set of questions through the real web_search tool and reports
found-rate (not NOT FOUND), latency, and how many answers name a source and a date. It does NOT judge correctness, because
that would need a stored answer key; read the printed answers yourself. Usage (on the Pi): python bench/search_eval.py"""
import asyncio
import re
import statistics
import time

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

QUESTIONS = [
    "what is the weather outlook news for Europe this week", "who is the current president of Indonesia",
    "what happened in the stock market today", "what is the latest news about electric cars",
    "when is the next full moon", "what is the newest smartphone from Samsung",
    "who won the most recent tennis grand slam", "what is the price of gold right now",
    "what is the latest news on the Philippine economy", "when does the next Premier League matchday start",
]


async def ask(q):
    async with streamable_http_client("http://127.0.0.1:8104/mcp") as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            t = time.monotonic()
            r = await s.call_tool("web_search", {"query": q})
            return time.monotonic() - t, r.content[0].text


async def main():
    rows = []
    for q in QUESTIONS:
        dt, txt = await ask(q)
        rows.append((q, dt, txt))
        print(f"[{dt:4.1f}s] {q}\n        {txt[:300]}\n")
    found = sum(not t.upper().startswith("NOT FOUND") and "found nothing" not in t for _, _, t in rows)
    dated = sum(bool(re.search(r"20\d\d|monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|november", t, re.I)) for _, _, t in rows)
    sourced = sum("Sources:" in t for _, _, t in rows)
    lat = sorted(d for _, d, _ in rows)
    print(f"found {found}/{len(rows)} | names a source {sourced}/{len(rows)} | mentions a date {dated}/{len(rows)} | "
          f"latency median {statistics.median(lat):.1f}s, max {lat[-1]:.1f}s")

asyncio.run(main())
