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
         "who is the current")
# Schedules and fixtures live on schedule PAGES, not in news articles: no news topic and no 'last month' filter for these.
SCHEDULE = ("next game", "next match", "upcoming", "schedule", "fixture", "tomorrow", "when is", "when does", "when's",
            "next concert", "next race")


async def _search(key: str, query: str, topic: str, time_range: str | None, deep: bool = False, raw: bool = False) -> dict:
    # Time-sensitive questions get the slower, more relevant 'basic' depth and 3 results (correctness over speed);
    # everything else stays on 'fast'.
    body = {"query": query, "max_results": 3 if deep else 2, "include_answer": True, "topic": topic,
            "search_depth": os.environ.get("SEARCH_DEPTH_NEWS", "basic") if deep else os.environ.get("SEARCH_DEPTH", "fast")}
    if raw:
        body["include_raw_content"] = True          # the page text itself, not just a snippet
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


PERSON_RX = re.compile(r"^(?:(?:about|on|who is|who's|information (?:about|on)|research|search for)\s+)?"
                       r"(?:(?:lord|dr|mr|ms|mrs|engr|atty)\.?\s+)?(?:[A-Z][\w'’.-]+\s+){1,3}[A-Z][\w'’.-]+\??$")


def looks_like_person(query: str) -> bool:
    """A query that is basically just a personal name (two to four capitalised words), or 'about me / myself'."""
    q = query.strip()
    return bool(PERSON_RX.match(q)) or bool(re.search(r"\b(about me|about myself|who am i)\b", q, re.I))


STOP = {"the", "and", "for", "what", "when", "who", "how", "are", "is", "was", "next", "latest", "current", "this", "that",
        "with", "from", "about", "tell", "give", "please", "game", "games", "today", "now"}
TZ_NAME = os.environ.get("TZ_NAME", "Asia/Manila")


def best_chunks(text: str, query: str, today: datetime.date, k: int = 3, size: int = 420) -> list[str]:
    """Pick the passages of a page that best match the question AND today's date (generic retrieval, no topic rules)."""
    words = {w for w in re.findall(r"[a-z0-9']+", query.lower()) if len(w) > 2} - STOP
    day_forms = {f"{today:%b} {today.day}".lower(), f"{today:%B} {today.day}".lower(), f"{today.day} {today:%B}".lower(),
                 f"{today:%A}".lower()}
    chunks = [text[i:i + size] for i in range(0, min(len(text), 14000), size - 80)]

    def score(c: str) -> int:
        cl = c.lower()
        return sum(cl.count(w) for w in words) + 3 * sum(1 for d in day_forms if d in cl)

    ranked = [c for c in sorted(chunks, key=score, reverse=True)[:k] if score(c) > 0]
    return [clean(c) for c in ranked]


@mcp.tool()
async def web_search(query: str) -> str:
    """Search the web for current information (news, schedules, results, facts). Reads the pages and returns the passages that
    match the question and today's date, with the outlet names and a note of the current time and time zone. Always returns the
    MOST RECENT information available; do not add a year to the query yourself. When searching for a person, results may be
    about someone else who shares the name: do not present a name-only match as fact, say it may not be them, and confirm a
    distinguishing detail (school, city, handle) with the user."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return "Search is not available because the search key is missing."
    from zoneinfo import ZoneInfo
    now = datetime.datetime.now(ZoneInfo(TZ_NAME))
    q = query if re.search(r"(19|20)\d{2}", query) else f"{query} {now.year}"
    ql = query.lower()
    sched = any(w in ql for w in SCHEDULE)
    newsy = any(w in ql for w in NEWSY) and not sched
    if sched:
        d = await _search(key, q, "general", None, deep=True, raw=True)
    else:
        d = await _search(key, q, "news" if newsy else "general", "month" if newsy else "year", deep=newsy, raw=True)
    if not d.get("results") and not d.get("answer"):
        d = await _search(key, q, "general", None, deep=True, raw=True)
    evidence, hosts = [], []
    for item in d.get("results", [])[:3]:
        host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", item.get("url", "")).split("/")[0])
        passages = best_chunks(item.get("raw_content") or "", query, now.date()) or [clean(item.get("content", ""))[:320]]
        pub = f", published {item['published_date'][:16]}" if item.get("published_date") else ""
        evidence.append(f"[{host}{pub}] " + " ... ".join(passages))
        if host and host not in hosts:
            hosts.append(host)
    if not evidence and not d.get("answer"):
        return "I found nothing useful for that search."
    header = (f"Now: {now:%A %d %B %Y, %I:%M %p} {TZ_NAME}. Times in the sources are as written by each source; "
              f"state which time zone you mean. ")
    text = header + (clean(d["answer"]) + " " if d.get("answer") else "") + " ".join(evidence)
    text = tag_past_dates(text)[:1900]
    if looks_like_person(query):
        text = ("CAUTION: this is a search for a person by name. These results may describe someone else who shares the "
                "name. Do not present them as facts about the user; say they may not be the same person and ask for a "
                "distinguishing detail. " + text)
    return text + (" Sources: " + ", ".join(hosts) + "." if hosts else "")


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
