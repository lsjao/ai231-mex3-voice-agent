"""search-mcp: our MCP server for web search via Tavily. Streamable HTTP on localhost:8104.

Tool: web_search(query) -> a short spoken-style answer read from the pages, with outlet names and dates. Generic pipeline,
no topic rules:  rewrite the spoken question into clean queries -> search in parallel -> drop low-quality domains, merge,
rerank -> a small fast model reads the page passages and answers ONLY from them -> if it says NOT FOUND, rewrite using what the
pages did contain and try again (up to two retries). URLs and markdown are stripped so the agent never reads them aloud.
"""
import asyncio
import datetime
import json
import os
import re
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()
PORT = int(os.environ.get("SEARCH_MCP_PORT", "8104"))
TZ_NAME = os.environ.get("TZ_NAME", "Asia/Manila")
SMALL_MODEL = os.environ.get("EXTRACT_MODEL", "google/gemini-2.5-flash-lite")   # rewriter, reranker and reader
MAX_RETRIES = int(os.environ.get("SEARCH_RETRIES", "1"))
FIRST_DEPTH = os.environ.get("SEARCH_DEPTH_FIRST", "fast")   # measured on the Pi: fast ~1.5 s, basic ~4.4 s, advanced ~7 s
BUDGET_S = float(os.environ.get("SEARCH_BUDGET_S", "9"))   # do not start another attempt after this many seconds
# Generic quality filter: short-video and social pages carry hashtags, not facts.
BAD_DOMAINS = ("tiktok.com", "youtube.com", "facebook.com", "instagram.com", "pinterest.com", "x.com", "twitter.com")
mcp = MCPServer("search-mcp")
_client = httpx.AsyncClient(timeout=15)
NL = chr(10)


def clean(text: str) -> str:
    text = re.sub(r"!?\((?:https?:)?/[^)\s]*\)", "", text)          # page-navigation link targets like (/games)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>\[\]]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def host_of(url: str) -> str:
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0])


# ---------------------------------------------------------------- date and time-zone helpers (done in code, not by the model)
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
_MON = "|".join(MONTHS)
DATE_PATTERNS = [
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\s*,?\s+(\d{{4}})\b", re.I), "dmy"),
    (re.compile(rf"\b({_MON})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s+(\d{{4}})\b", re.I), "mdy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(rf"\b({_MON})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{{4}})", re.I), "md"),   # no year: assume this year
]


def tag_past_dates(text: str, today: datetime.date | None = None) -> str:
    """Add '(already in the past)' after full dates earlier than yesterday (one day of slack for time zones). Small models
    are poor at comparing dates, so the comparison is done here."""
    today = today or datetime.date.today()
    hits = []
    for rx, kind in DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                if kind == "dmy":
                    d = datetime.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
                elif kind == "md":
                    d = datetime.date(today.year, MONTHS[m.group(1).lower()], int(m.group(2)))
                elif kind == "mdy":
                    d = datetime.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
                else:
                    d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            if d < today - datetime.timedelta(days=1):
                hits.append(m.end())
    for pos in sorted(set(hits), reverse=True):
        text = text[:pos] + " (already in the past)" + text[pos:]
    return text


ZONES = {"ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York", "CT": "America/Chicago",
         "CST": "America/Chicago", "CDT": "America/Chicago", "MT": "America/Denver", "MST": "America/Denver",
         "MDT": "America/Denver", "PT": "America/Los_Angeles", "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
         "UTC": "UTC", "GMT": "UTC", "BST": "Europe/London"}
TIME_RX = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\s*(ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|UTC|GMT|BST)", re.I)


def annotate_times(text: str, user_tz: str = TZ_NAME) -> str:
    """Small models are poor at time-zone arithmetic, so do it in code: '7:30 a.m. ET' -> '7:30 a.m. ET (= 12:30 UTC / 08:30 PM Manila)'."""
    today = datetime.datetime.now(ZoneInfo(user_tz)).date()

    def conv(m):
        h, mi, ap, z = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower(), m.group(4).upper()
        if not 1 <= h <= 12:
            return m.group(0)
        h = h % 12 + (12 if ap == "p" else 0)
        src = datetime.datetime(today.year, today.month, today.day, h, mi, tzinfo=ZoneInfo(ZONES[z]))
        utc, loc = src.astimezone(ZoneInfo("UTC")), src.astimezone(ZoneInfo(user_tz))
        return f"{m.group(0)} (= {utc:%H:%M} UTC / {loc:%I:%M %p} {user_tz.split('/')[-1].replace('_', ' ')})"

    return TIME_RX.sub(conv, text)


PERSON_RX = re.compile(r"^(?:(?:about|on|who is|who's|information (?:about|on)|research|search for)\s+)?"
                       r"(?:(?:lord|dr|mr|ms|mrs|engr|atty)\.?\s+)?(?:[A-Z][\w'’.-]+\s+){1,3}[A-Z][\w'’.-]+\??$")


def looks_like_person(query: str) -> bool:
    q = query.strip()
    return bool(PERSON_RX.match(q)) or bool(re.search(r"\b(about me|about myself|who am i)\b", q, re.I))


CAUTION = ("CAUTION: this is a search for a person by name. These results may describe someone else who shares the name. "
           "Do not present them as facts about the user; say they may not be the same person and ask for a distinguishing "
           "detail. ")

STOP = {"the", "and", "for", "what", "when", "who", "how", "are", "is", "was", "next", "latest", "current", "this", "that",
        "with", "from", "about", "tell", "give", "please", "game", "games", "today", "now"}


def best_chunks(text: str, query: str, today: datetime.date, k: int = 3, size: int = 420) -> list[str]:
    """Passages of a page that best match the question AND today's date (generic retrieval, no topic rules)."""
    words = {w for w in re.findall(r"[a-z0-9']+", query.lower()) if len(w) > 2} - STOP
    day_forms = {f"{today:%b} {today.day}".lower(), f"{today:%B} {today.day}".lower(), f"{today.day} {today:%B}".lower(),
                 f"{today:%A}".lower()}
    chunks = [text[i:i + size] for i in range(0, min(len(text), 20000), size - 80)]

    def score(c: str) -> int:
        cl = c.lower()
        return sum(cl.count(w) for w in words) + 3 * sum(1 for d in day_forms if d in cl)

    ranked = [c for c in sorted(chunks, key=score, reverse=True)[:k] if score(c) > 0]
    out = [clean(c) for c in ranked]
    return [c for c in out if sum(ch.isalnum() for ch in c) > 0.55 * max(len(c), 1)]   # drop mostly-symbol passages


def _trace(now, query: str, hosts: list, out: str, note: str = "") -> None:
    """Raw trace so a bad answer can be pinned on retrieval (here) or on the model (what it said after)."""
    try:
        import pathlib
        f = pathlib.Path(__file__).resolve().parent.parent / "logs" / "search_trace.jsonl"
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": now.isoformat(timespec="seconds"), "query": query, "sources": hosts, "note": note,
                                 "result": out}) + NL)
    except Exception:
        pass


# ---------------------------------------------------------------- small-model steps
async def small(system: str, user: str, max_tokens: int = 220) -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        r = await _client.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                               json={"model": SMALL_MODEL, "temperature": 0, "max_tokens": max_tokens,
                                     "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                               timeout=12)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


REWRITE_PROMPT = (
    "You turn a spoken question into web search queries. The question may contain filler words and speech-recognition noise. "
    "Write 2 short queries with different wording that name the specific thing asked for (entity, and the quantity or "
    "attribute wanted, such as a score, a price, a time, a name, a number). When the question uses a relative time such as "
    "today, tonight, latest, current or next, put the explicit date, month or year in the queries using the current date given. "
    "Also decide news: true only if the person wants reporting on recent events, false for schedules, prices, facts and "
    "everything else. Reply with JSON only: {\"queries\": [\"...\", \"...\"], \"news\": true|false}")


async def rewrite(query: str, now: datetime.datetime, hint: str = "") -> tuple[list[str], bool]:
    user = f"Current date: {now:%A %d %B %Y}. Time zone of the person: {TZ_NAME}.{NL}Spoken question: {query}"
    if hint:
        user += f"{NL}A previous search did not find the answer. The pages it read were about: {hint}{NL}Write different queries."
    raw = await small(REWRITE_PROMPT, user, 160)
    try:
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        qs = [str(q).strip() for q in data["queries"] if str(q).strip()][:2]
        if qs:
            return qs, bool(data.get("news"))
    except Exception:
        pass
    return [query if re.search(r"(19|20)\d{2}", query) else f"{query} {now.year}"], False


async def tavily(key: str, q: str, news: bool, depth: str) -> list[dict]:
    body = {"query": q, "max_results": 5, "include_answer": False, "include_raw_content": True,
            "topic": "news" if news else "general", "search_depth": depth}
    if news:
        body["time_range"] = "month"
    try:
        r = await _client.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"}, json=body)
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception:
        return []


async def gather(key: str, queries: list[str], news: bool, depth: str) -> list[dict]:
    """Search every query in parallel, drop low-quality domains, merge duplicates (best score wins)."""
    batches = await asyncio.gather(*(tavily(key, q, news, depth) for q in queries))
    merged: dict[str, dict] = {}
    for results in batches:
        for item in results:
            url = item.get("url", "")
            if not url or any(host_of(url).endswith(b) for b in BAD_DOMAINS):
                continue
            if url not in merged or item.get("score", 0) > merged[url].get("score", 0):
                merged[url] = item
    return sorted(merged.values(), key=lambda i: i.get("score", 0), reverse=True)


RERANK_PROMPT = ("Pick the pages most likely to contain the answer to the question: prefer reputable, recent pages that match "
                 "what was asked, and avoid pages about a different subject. Reply with JSON only: {\"best\": [numbers]} "
                 "listing at most 3 page numbers, best first.")


async def rerank(query: str, now: datetime.datetime, cands: list[dict]) -> list[dict]:
    cands = cands[:8]
    if len(cands) <= 3 or os.environ.get("SEARCH_RERANK", "0") != "1":   # off by default: costs ~1 s, value not measured
        return cands[:3]
    listing = NL.join(f"{i + 1}. {host_of(c['url'])} | {(c.get('published_date') or 'no date')[:16]} | "
                      f"{clean(c.get('title', ''))[:90]} | {clean(c.get('content', ''))[:160]}" for i, c in enumerate(cands))
    raw = await small(RERANK_PROMPT, f"Current date: {now:%d %B %Y}.{NL}Question: {query}{NL}{listing}", 40)
    try:
        idx = [int(n) - 1 for n in json.loads(re.search(r"\{.*\}", raw, re.S).group(0))["best"]]
        picked = [cands[i] for i in idx if 0 <= i < len(cands)]
        if picked:
            return picked[:3]
    except Exception:
        pass
    return cands[:3]


READ_PROMPT = (
    "You read web pages to answer one spoken question. Use ONLY the page text below; never use your own memory. "
    "Answer in at most three plain sentences that can be read aloud: no lists, symbols or links. "
    "Give the specific facts asked for (names, numbers, times, results) and say which source and date they come from. "
    "Always state the time zone of any time; use the conversions written in brackets when present, and if the question asks "
    "for a different zone than the page uses, say what zone the page uses, and never state how zones relate to each other unless a page says so. Prefer the most recent information, and notice "
    "dates that are already past compared with the current date. Answer exactly what was asked: if a page is about a "
    "different event, year, measure or moment than the question (for example a different year's schedule, or odds for a "
    "different outcome), do not use it, or say how it differs. If a source gives no date, say its date is unknown. When "
    "sources disagree on a number, give the one with the newest as-of date and say the others differ. If the pages do not "
    "contain the asked-for fact, reply starting with NOT FOUND and say briefly what the pages do contain.")


def passages(item: dict, query: str, today: datetime.date) -> str:
    body = " ... ".join(best_chunks(item.get("raw_content") or "", query, today, k=5, size=900)) or clean(item.get("content", ""))
    return annotate_times(tag_past_dates(body[:3500], today))


async def read(query: str, now: datetime.datetime, pages: list[dict]) -> str | None:
    blocks = []
    for i, it in enumerate(pages):
        pub = f"(published {it['published_date'][:16]})" if it.get("published_date") else ""
        blocks.append(f"SOURCE {i + 1}: {host_of(it['url'])} {pub}{NL}{passages(it, query, now.date())}")
    user = (f"Current date and time: {now:%A %d %B %Y, %I:%M %p} {TZ_NAME}." + NL + f"Question: {query}" + NL * 2
            + (NL * 2).join(blocks))
    ans = await small(READ_PROMPT, user, 220)
    return clean(ans) if ans else None


# ---------------------------------------------------------------- the tool
@mcp.tool()
async def web_search(query: str) -> str:
    """Search the web for current information (news, schedules, results, prices, facts). Rewrites the question into good
    queries, reads the pages, and answers only from them, naming the outlets and dates. If the answer starts with NOT FOUND,
    the pages did not contain it. Always returns the MOST RECENT information available; do not add a year to the query
    yourself. When searching for a person, results may be about someone else who shares the name: do not present a name-only
    match as fact, say it may not be them, and confirm a distinguishing detail (school, city, handle) with the user."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return "Search is not available because the search key is missing."
    now = datetime.datetime.now(ZoneInfo(TZ_NAME))
    hint, answer, hosts, note = "", None, [], ""
    started = asyncio.get_event_loop().time()
    for attempt in range(MAX_RETRIES + 1):
        if attempt and asyncio.get_event_loop().time() - started > BUDGET_S:
            break
        queries, news = await rewrite(query, now, hint)
        cands = await gather(key, queries, news, FIRST_DEPTH if attempt == 0 else "basic")   # fast first (~1.5 s), deeper only if needed
        if not cands and news:                      # nothing recent: retry without the news filter
            cands = await gather(key, queries, False, FIRST_DEPTH)
        if not cands:
            hint, note = "nothing at all", f"attempt {attempt}: no pages for {queries}"
            continue
        top = await rerank(query, now, cands)
        hosts = list(dict.fromkeys(host_of(c["url"]) for c in top))
        answer = await read(query, now, top)
        note = f"attempt {attempt}: queries={queries} news={news}"
        if answer and not answer.upper().startswith("NOT FOUND"):
            break
        hint = (answer or "unrelated material")[:200]
    if not answer:
        out = "I found nothing useful for that search."
    else:
        out = answer + (" Sources: " + ", ".join(hosts) + "." if hosts else "")
        if looks_like_person(query):
            out = CAUTION + out
    _trace(now, query, hosts, out, note)
    return out


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
