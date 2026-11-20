"""search-mcp: our MCP server for web search via Tavily. Streamable HTTP on localhost:8104.

Tool: web_search(query) -> a short spoken-style answer plus the top headlines. URLs and markdown are stripped
so the voice agent never reads them aloud.
"""
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


@mcp.tool()
async def web_search(query: str) -> str:
    """Search the web for current information (news, facts, recent events). Returns a brief summary."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return "Search is not available because the search key is missing."
    r = await _client.post("https://api.tavily.com/search",
                           headers={"Authorization": f"Bearer {key}"},
                           json={"query": query, "max_results": 3, "include_answer": True, "search_depth": "basic"})
    r.raise_for_status()
    d = r.json()
    parts = []
    if d.get("answer"):
        parts.append(clean(d["answer"]))
    for item in d.get("results", [])[:3]:
        title, snippet = clean(item.get("title", "")), clean(item.get("content", ""))[:160]
        if title:
            parts.append(f"{title}: {snippet}" if snippet else title)
    return " ".join(parts)[:900] or "I found nothing useful for that search."


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
