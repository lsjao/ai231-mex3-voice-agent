"""asr-mcp: our MCP server wrapping Deepgram speech-to-text. Runs on the Pi, streamable HTTP on localhost.

Tool: transcribe(audio_b64, sample_rate) -> text. Audio is base64 PCM16 mono (the VAD-bounded utterance).
Batch (prerecorded) REST call, not streaming: one HTTP round trip after the turn ends. See docs/PLAN.md.
Set ASR_MOCK=1 to return canned text without any network or key (for wiring tests).
"""
import base64, os, time
import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()
PORT = int(os.environ.get("ASR_MCP_PORT", "8101"))
MODEL = os.environ.get("DEEPGRAM_ASR_MODEL", "nova-3")
mcp = MCPServer("asr-mcp")
_client = httpx.AsyncClient(timeout=15)  # reused: keeps the TLS connection warm between turns


@mcp.tool()
async def transcribe(audio_b64: str, sample_rate: int = 16000) -> str:
    """Transcribe one utterance of base64-encoded 16-bit mono PCM and return the text."""
    if os.environ.get("ASR_MOCK") == "1":
        return os.environ.get("ASR_MOCK_TEXT", "this is a mock transcript")
    key = os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY is not set")
    pcm = base64.b64decode(audio_b64)
    t0 = time.monotonic()
    r = await _client.post(
        "https://api.deepgram.com/v1/listen",
        params={"model": MODEL, "smart_format": "true", "language": "en",
                "encoding": "linear16", "sample_rate": sample_rate, "channels": 1},
        headers={"Authorization": f"Token {key}", "Content-Type": "application/octet-stream"},
        content=pcm,
    )
    r.raise_for_status()
    text = r.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
    print(f"[asr-mcp] {len(pcm)/2/sample_rate:.1f}s audio -> {time.monotonic()-t0:.2f}s: {text!r}", flush=True)
    return text


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
