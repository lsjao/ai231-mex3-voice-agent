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


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
