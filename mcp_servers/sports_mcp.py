"""sports-mcp: structured scores and schedules for many leagues (not just the NBA). Streamable HTTP on localhost:8108.

Why a dedicated tool: web search returns ARTICLES, the wrong shape for 'what is the score' or 'when is the next game'; the agent
answered those with contradictory kickoff times. This reads ESPN's public scoreboard JSON (no key) and converts every start time
to an EXPLICIT time zone (default Asia/Manila; the caller can pass e.g. Europe/London for 'UK time'), so there is no guessing.
Tools: sports_games(league, when, timezone) for one day; sports_next_games(league, timezone) for what is coming up.
"""
import datetime as dt
import os
from zoneinfo import ZoneInfo

import httpx
from mcp.server.mcpserver import MCPServer

PORT = int(os.environ.get("SPORTS_MCP_PORT", "8108"))
DEFAULT_TZ = os.environ.get("TZ_NAME", "Asia/Manila")
BASE = "https://site.api.espn.com/apis/site/v2/sports"
LEAGUES = {  # spoken name -> ESPN path
    "nba": "basketball/nba", "basketball": "basketball/nba", "wnba": "basketball/wnba",
    "nfl": "football/nfl", "mlb": "baseball/mlb", "nhl": "hockey/nhl",
    "premier league": "soccer/eng.1", "epl": "soccer/eng.1", "english premier league": "soccer/eng.1",
    "la liga": "soccer/esp.1", "serie a": "soccer/ita.1", "bundesliga": "soccer/ger.1", "ligue 1": "soccer/fra.1",
    "champions league": "soccer/uefa.champions", "europa league": "soccer/uefa.europa", "mls": "soccer/usa.1",
    "world cup": "soccer/fifa.world",
}
mcp = MCPServer("sports-mcp")
_client = httpx.AsyncClient(timeout=10)


def resolve(league: str) -> tuple[str, str] | None:
    key = league.strip().lower()
    for name, path in LEAGUES.items():
        if key == name or key in name or name in key:
            return name, path
    return None


async def fetch_day(path: str, d: dt.date, tz: ZoneInfo) -> list[dict]:
    r = await _client.get(f"{BASE}/{path}/scoreboard", params={"dates": d.strftime("%Y%m%d")})
    r.raise_for_status()
    games = []
    for ev in r.json().get("events", []):
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        st = ev["status"]["type"]
        games.append({"start": dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(tz),
                      "state": st["state"], "detail": st.get("shortDetail", ""),
                      "away": teams["away"]["team"]["displayName"], "home": teams["home"]["team"]["displayName"],
                      "away_score": teams["away"].get("score"), "home_score": teams["home"].get("score")})
    return games


def say_time(t: dt.datetime) -> str:
    return t.strftime("%A %I:%M %p").replace(" 0", " ")


def describe(g: dict, tzname: str) -> str:
    if g["state"] == "post":
        a, h = int(g["away_score"] or 0), int(g["home_score"] or 0)
        if a == h:
            return f"{g['away']} and {g['home']} drew {a} to {h}, final"
        w, l = ((g["away"], g["home"]) if a > h else (g["home"], g["away"]))
        return f"{w} beat {l}, {max(a, h)} to {min(a, h)}, final"
    if g["state"] == "in":
        return f"{g['away']} {g['away_score']}, {g['home']} {g['home_score']}, live, {g['detail']}"
    return f"{g['away']} at {g['home']}, {say_time(g['start'])} {tzname} time"


async def window(path: str, center: dt.date, tz: ZoneInfo, back: int = 1, ahead: int = 1) -> list[dict]:
    out = []
    for i in range(-back, ahead + 1):
        out += await fetch_day(path, center + dt.timedelta(days=i), tz)
    seen, uniq = set(), []
    for g in sorted(out, key=lambda x: x["start"]):          # a game can appear under two US dates
        key = (g["away"], g["home"], g["start"])
        if key not in seen:
            seen.add(key)
            uniq.append(g)
    return uniq


def prepare(league: str, timezone: str):
    found = resolve(league)
    if not found:
        return None, None, None, f"I do not have {league}. I cover: " + ", ".join(sorted({n for n in LEAGUES})) + "."
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        return None, None, None, f"I do not know the time zone {timezone}."
    return found, tz, timezone.split("/")[-1].replace("_", " "), None


@mcp.tool()
async def sports_games(league: str = "nba", when: str = "today", timezone: str = DEFAULT_TZ) -> str:
    """Games for one calendar day in a league: final scores, live scores, and start times for games still to come, in the given
    time zone. league: nba, nfl, mlb, nhl, premier league, la liga, serie a, bundesliga, champions league, mls, world cup.
    when: today, yesterday, tomorrow, or a date like 2026-11-24. timezone: e.g. Asia/Manila (default) or Europe/London for UK time."""
    found, tz, label, err = prepare(league, timezone)
    if err:
        return err
    today = dt.datetime.now(tz).date()
    w = when.strip().lower()
    day = {"today": today, "yesterday": today - dt.timedelta(days=1), "tomorrow": today + dt.timedelta(days=1)}.get(w)
    if day is None:
        try:
            day = dt.date.fromisoformat(w)
        except ValueError:
            return "I did not understand that date. Try today, yesterday, tomorrow, or a date like 2026-11-24."
    try:
        games = [g for g in await window(found[1], day, tz) if g["start"].date() == day]
    except Exception:
        return f"I could not reach the {found[0]} scoreboard right now."
    if not games:
        return f"There are no {found[0]} games on {day:%A, %B %d} in {label} time."
    return (f"{found[0]} games on {day:%A, %B %d}, {label} time: " + "; ".join(describe(g, label) for g in games[:8]) + ".")


@mcp.tool()
async def sports_next_games(league: str = "nba", timezone: str = DEFAULT_TZ) -> str:
    """The next upcoming games in a league (plus any live right now) with start times in the given time zone."""
    found, tz, label, err = prepare(league, timezone)
    if err:
        return err
    now = dt.datetime.now(tz)
    try:
        games = [g for g in await window(found[1], now.date(), tz, back=0, ahead=6) if g["state"] != "post"]
    except Exception:
        return f"I could not reach the {found[0]} scoreboard right now."
    live = [g for g in games if g["state"] == "in"]
    nxt = [g for g in games if g["state"] == "pre"][:5]
    if not live and not nxt:
        return f"I could not find any upcoming {found[0]} games in the next week."
    parts = []
    if live:
        parts.append("Live right now: " + "; ".join(describe(g, label) for g in live[:3]))
    if nxt:
        parts.append("Next up: " + "; ".join(describe(g, label) for g in nxt))
    return ". ".join(parts) + "."


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
