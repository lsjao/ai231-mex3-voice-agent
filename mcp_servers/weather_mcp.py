"""weather-mcp: our MCP server for live weather via Open-Meteo (free, no API key). Streamable HTTP on localhost:8103.

Tool: get_weather(city) -> one short spoken-style sentence (no markdown, no URLs), safe to read aloud.
"""
import os

import httpx
from mcp.server.mcpserver import MCPServer

PORT = int(os.environ.get("WEATHER_MCP_PORT", "8103"))
mcp = MCPServer("weather-mcp")
_client = httpx.AsyncClient(timeout=10)

# WMO weather codes -> words
WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers",
       82: "heavy rain showers", 95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail"}


@mcp.tool()
async def get_weather(city: str) -> str:
    """Get the current weather and today's outlook for a city, e.g. 'Manila' or 'Tokyo'."""
    g = await _client.get("https://geocoding-api.open-meteo.com/v1/search",
                          params={"name": city, "count": 1, "language": "en"})
    g.raise_for_status()
    hits = g.json().get("results") or []
    if not hits:
        return f"I couldn't find a place called {city}."
    place = hits[0]
    w = await _client.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": 1,
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
    w.raise_for_status()
    d = w.json()
    cur, day = d["current"], d["daily"]
    sky = WMO.get(cur["weather_code"], "unsettled")
    name = place["name"] + (f", {place['country']}" if place.get("country") else "")
    return (f"In {name} it is {round(cur['temperature_2m'])} degrees Celsius and {sky} right now, "
            f"with a high of {round(day['temperature_2m_max'][0])} and a low of {round(day['temperature_2m_min'][0])} today. "
            f"The chance of rain is {day['precipitation_probability_max'][0]} percent.")


@mcp.tool()
async def get_current_time(timezone: str = "Asia/Manila") -> str:
    """The current local time and date from the device clock, for a time zone like Asia/Manila, America/New_York or Europe/London."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    try:
        now = _dt.datetime.now(ZoneInfo(timezone))
    except Exception:
        return f"I do not know the time zone {timezone}."
    city = timezone.split("/")[-1].replace("_", " ")
    return f"It is {now:%I:%M %p}".replace("It is 0", "It is ") + f" on {now:%A, %d %B %Y} in {city}."


@mcp.tool()
async def convert_time(time: str, from_timezone: str, to_timezone: str = "Asia/Manila", date: str = "") -> str:
    """Convert a clock time from one time zone to another and say which day it lands on. Use this instead of working it out
    yourself. time: like '8:00 PM' or '20:00'. from_timezone / to_timezone: like America/Los_Angeles, Europe/London, Asia/Manila.
    date: optional YYYY-MM-DD in the FROM zone (default: today there)."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    try:
        src_tz, dst_tz = ZoneInfo(from_timezone), ZoneInfo(to_timezone)
    except Exception:
        return "I do not know one of those time zones."
    t = time.strip().upper().replace(".", "")
    parsed = None
    for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M"):
        try:
            parsed = _dt.datetime.strptime(t, fmt).time()
            break
        except ValueError:
            continue
    if parsed is None:
        return "I could not read that time."
    try:
        day = _dt.date.fromisoformat(date) if date else _dt.datetime.now(src_tz).date()
    except ValueError:
        return "I could not read that date."
    src = _dt.datetime.combine(day, parsed, tzinfo=src_tz)
    dst = src.astimezone(dst_tz)
    shift = (dst.date() - src.date()).days
    when = {0: "the same day", 1: "the next day", -1: "the previous day"}.get(shift, f"{shift:+d} days")
    f = lambda d, z: f"{d:%I:%M %p}".lstrip("0") + " " + z.split("/")[-1].replace("_", " ") + " time"
    return f"{f(src, from_timezone)} on {src:%A, %d %B} is {f(dst, to_timezone)} on {dst:%A, %d %B}, {when}."


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
