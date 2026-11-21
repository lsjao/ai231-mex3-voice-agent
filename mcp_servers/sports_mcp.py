"""sports-mcp: structured NBA data (scores, live games, upcoming schedule) for the voice agent. Streamable HTTP on localhost:8108.

Why a dedicated tool: web search returns articles, which is the wrong shape for 'when is the next game' or 'what is the score'
(the agent answered schedule questions with vague headlines and no dates). This reads ESPN's public scoreboard JSON (no key) and
converts every start time to the user's time zone (default Asia/Manila), so answers are specific and current.
Tools: nba_games(when) for one day, nba_next_games() for the next few upcoming games.
"""
import datetime as dt
import os
from zoneinfo import ZoneInfo

import httpx
from mcp.server.mcpserver import MCPServer

PORT = int(os.environ.get("SPORTS_MCP_PORT", "8108"))
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Manila"))
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
mcp = MCPServer("sports-mcp")
_client = httpx.AsyncClient(timeout=10)


async def fetch_day(d: dt.date) -> list[dict]:
    r = await _client.get(URL, params={"dates": d.strftime("%Y%m%d")})
    r.raise_for_status()
    games = []
    for ev in r.json().get("events", []):
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        start = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(TZ)
        st = ev["status"]["type"]
        games.append({"start": start, "state": st["state"], "detail": st.get("shortDetail", ""),
                      "away": teams["away"]["team"]["displayName"], "home": teams["home"]["team"]["displayName"],
                      "away_score": teams["away"].get("score"), "home_score": teams["home"].get("score")})
    return games


def say_time(t: dt.datetime) -> str:
    return t.strftime("%A %I:%M %p").replace(" 0", " ")


def describe(g: dict) -> str:
    if g["state"] == "post":
        a, h = int(g["away_score"]), int(g["home_score"])
        w, l = ((g["away"], g["home"]) if a > h else (g["home"], g["away"]))
        return f"{w} beat {l}, {max(a, h)} to {min(a, h)}, final"
    if g["state"] == "in":
        return f"{g['away']} {g['away_score']}, {g['home']} {g['home_score']}, live, {g['detail']}"
    return f"{g['away']} at {g['home']}, {say_time(g['start'])} your time"


async def window(center: dt.date, back: int = 1, ahead: int = 1) -> list[dict]:
    out = []
    for i in range(-back, ahead + 1):
        out += await fetch_day(center + dt.timedelta(days=i))
    seen, uniq = set(), []
    for g in sorted(out, key=lambda x: x["start"]):          # the same game can appear under two US dates
        key = (g["away"], g["home"], g["start"])
        if key not in seen:
            seen.add(key)
            uniq.append(g)
    return uniq


@mcp.tool()
async def nba_games(when: str = "today") -> str:
    """NBA games on one calendar day in the user's time zone: scores for finished games, live scores, and start times for
    games still to come. 'when' is today, yesterday, tomorrow, or a date like 2026-11-24."""
    today = dt.datetime.now(TZ).date()
    w = when.strip().lower()
    day = {"today": today, "yesterday": today - dt.timedelta(days=1), "tomorrow": today + dt.timedelta(days=1)}.get(w)
    if day is None:
        try:
            day = dt.date.fromisoformat(w)
        except ValueError:
            return "I did not understand that date. Try today, yesterday, tomorrow, or a date like 2026-11-24."
    try:
        games = [g for g in await window(day) if g["start"].date() == day]
    except Exception:
        return "I could not reach the NBA scoreboard right now."
    if not games:
        return f"There are no NBA games on {day:%A, %B %d}."
    return f"NBA games on {day:%A, %B %d}, your time: " + "; ".join(describe(g) for g in games[:8]) + "."


@mcp.tool()
async def nba_next_games() -> str:
    """The next upcoming NBA games (including any live right now) with start times in the user's time zone."""
    now = dt.datetime.now(TZ)
    try:
        games = [g for g in await window(now.date(), back=0, ahead=6) if g["state"] != "post"]
    except Exception:
        return "I could not reach the NBA scoreboard right now."
    if not games:
        return "I could not find any upcoming NBA games in the next week."
    live = [g for g in games if g["state"] == "in"]
    nxt = [g for g in games if g["state"] == "pre"][:5]
    parts = []
    if live:
        parts.append("Live right now: " + "; ".join(describe(g) for g in live[:3]))
    if nxt:
        parts.append("Next up: " + "; ".join(describe(g) for g in nxt))
    return ". ".join(parts) + "."


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
