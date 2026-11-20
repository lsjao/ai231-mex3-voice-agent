"""tts-mcp: our MCP server wrapping Deepgram Aura-2 text-to-speech. Runs on the Pi, streamable HTTP on localhost.

Tool: speak(text, sample_rate) -> base64 PCM16 mono. The agent calls it once per sentence so the first audio
arrives after one REST round trip (TTFB); barge-in cancels the in-flight call. See docs/PLAN.md.
Set TTS_MOCK=1 to return a short tone without network or key (for wiring tests).
"""
import base64, math, os, struct, time
import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()
PORT = int(os.environ.get("TTS_MCP_PORT", "8102"))
MODEL = os.environ.get("DEEPGRAM_TTS_MODEL", "aura-2-thalia-en")
mcp = MCPServer("tts-mcp")
_client = httpx.AsyncClient(timeout=15)


@mcp.tool()
async def speak(text: str, sample_rate: int = 24000) -> str:
    """Synthesize text; returns base64-encoded 16-bit mono PCM at sample_rate."""
    if os.environ.get("TTS_MOCK") == "1":
        n = int(sample_rate * 0.4)
        pcm = b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 440 * i / sample_rate))) for i in range(n))
        return base64.b64encode(pcm).decode()
    key = os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY is not set")
    t0 = time.monotonic()
    r = await _client.post(
        "https://api.deepgram.com/v1/speak",
        params={"model": MODEL, "encoding": "linear16", "sample_rate": sample_rate, "container": "none"},
        headers={"Authorization": f"Token {key}", "Content-Type": "application/json"},
        json={"text": text},
    )
    r.raise_for_status()
    print(f"[tts-mcp] {len(text)} chars -> {len(r.content)/2/sample_rate:.1f}s audio in {time.monotonic()-t0:.2f}s", flush=True)
    return base64.b64encode(r.content).decode()


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
