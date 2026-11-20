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
         "now", "this week", "this year", "update", "recent", "happened", "winner", "standings", "price",
         "next", "upcoming", "schedule", "fixture", "tomorrow", "when is", "when does", "who is the current")


async def _search(key: str, query: str, topic: str, time_range: str | None, deep: bool = False) -> dict:
    # Time-sensitive questions get the slower, more relevant 'basic' depth and 3 results (correctness over speed);
    # everything else stays on 'fast'.
    body = {"query": query, "max_results": 3 if deep else 2, "include_answer": True, "topic": topic,
            "search_depth": os.environ.get("SEARCH_DEPTH_NEWS", "basic") if deep else os.environ.get("SEARCH_DEPTH", "fast")}
    if time_range:
        body["time_range"] = time_range
    r = await _client.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"}, json=body)
    r.raise_for_status()
    return r.json()


MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
_MON = "|".join(MONTHS)
DATE_PATTERNS = [  # (regex, how to read the groups)
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\s*,?\s+(\d{{4}})\b", re.I), "dmy"),
    (re.compile(rf"\b({_MON})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s+(\d{{4}})\b", re.I), "mdy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]


def tag_past_dates(text: str, today: datetime.date | None = None) -> str:
    """Add '(already in the past)' after any full date in the text that is earlier than today. Small models are poor at
    comparing dates, and a past date presented as 'upcoming' sounds confidently wrong, so we do the comparison in code."""
    today = today or datetime.date.today()
    hits = []
    for rx, kind in DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                if kind == "dmy":
                    d = datetime.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
                elif kind == "mdy":
                    d = datetime.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
                else:
                    d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            if d < today:
                hits.append(m.end())
    for pos in sorted(set(hits), reverse=True):
        text = text[:pos] + " (already in the past)" + text[pos:]
    return text


@mcp.tool()
async def web_search(query: str) -> str:
    """Search the web for current information (news, facts, recent events). Always returns the MOST RECENT
    information available; do not add a year to the query yourself. When searching for a person, results may be about
    someone else who shares the name: do not present a name-only match as fact, say it may not be them, and confirm a
    distinguishing detail (school, city, handle) with the user."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return "Search is not available because the search key is missing."
    year = datetime.date.today().year
    # Recency by default: put the current year in the query, use the news topic for time-sensitive questions, and
    # only look at recent pages. If that finds nothing, fall back to an unrestricted search.
    q = query if re.search(r"(19|20)\d{2}", query) else f"{query} {year}"
    newsy = any(w in query.lower() for w in NEWSY)
    d = await _search(key, q, "news" if newsy else "general", "month" if newsy else "year", deep=newsy)
    if not d.get("results") and not d.get("answer"):
        d = await _search(key, q, "general", None, deep=newsy)
    parts = []
    if d.get("answer"):
        parts.append(clean(d["answer"]))
    for item in d.get("results", [])[:2]:
        title, snippet = clean(item.get("title", "")), clean(item.get("content", ""))[:100]
        if title:
            parts.append(f"{title}: {snippet}" if snippet else title)
    return tag_past_dates(" ".join(parts))[:600] or "I found nothing useful for that search."


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
