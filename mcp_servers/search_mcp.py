"""search-mcp: our MCP server for web search via Tavily. Streamable HTTP on localhost:8104.

Tool: web_search(query) -> a short spoken-style answer plus the top headlines. URLs and markdown are stripped
so the voice agent never reads them aloud.
"""
import datetime
import os
import re

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()
PORT = int(os.environ.get("SEARCH_MCP_PORT", "8104"))
mcp = MCPServer("search-mcp")
_client = httpx.AsyncClient(timeout=15)


def clean(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>\[\]]", "", text)
    return re.sub(r"\s+", " ", text).strip()


NEWSY = ("latest", "news", "today", "tonight", "yesterday", "election", "score", "won", "wins", "result", "current",
         "now", "this week", "this year", "update", "recent", "happened", "winner", "standings", "price")


async def _search(key: str, query: str, topic: str, time_range: str | None) -> dict:
    body = {"query": query, "max_results": 2, "include_answer": True, "topic": topic,
            "search_depth": os.environ.get("SEARCH_DEPTH", "fast")}
    if time_range:
        body["time_range"] = time_range
    r = await _client.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"}, json=body)
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def web_search(query: str) -> str:
    """Search the web for current information (news, facts, recent events). Always returns the MOST RECENT
    information available; do not add a year to the query yourself."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return "Search is not available because the search key is missing."
    year = datetime.date.today().year
    # Recency by default: put the current year in the query, use the news topic for time-sensitive questions, and
    # only look at recent pages. If that finds nothing, fall back to an unrestricted search.
    q = query if re.search(r"(19|20)\d{2}", query) else f"{query} {year}"
    newsy = any(w in query.lower() for w in NEWSY)
    d = await _search(key, q, "news" if newsy else "general", "month" if newsy else "year")
    if not d.get("results") and not d.get("answer"):
        d = await _search(key, q, "general", None)
    parts = []
    if d.get("answer"):
        parts.append(clean(d["answer"]))
    for item in d.get("results", [])[:2]:
        title, snippet = clean(item.get("title", "")), clean(item.get("content", ""))[:100]
        if title:
            parts.append(f"{title}: {snippet}" if snippet else title)
    return " ".join(parts)[:550] or "I found nothing useful for that search."


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
