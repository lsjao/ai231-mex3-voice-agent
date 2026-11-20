"""asr-mcp: our MCP server wrapping Deepgram streaming speech-to-text. Runs on the Pi, streamable HTTP on localhost.

Why streaming: the Pi is ~240 ms (RTT) from Deepgram, so a batch upload after the turn ends costs several round trips.
We keep ONE warm Deepgram WebSocket and forward audio while the user is still speaking; at turn end the final
transcript is nearly ready.

Tools (one utterance at a time):
  asr_start()            reset the utterance buffer, make sure the WebSocket is up (warm)
  asr_push(audio_b64)    forward a chunk of base64 PCM16 mono 16 kHz audio
  asr_finish() -> text   flush Deepgram, wait for the final transcript, return it
  transcribe(audio_b64)  convenience: start + push + finish for a whole clip (used by tests)
Set ASR_MOCK=1 for canned text without network or key.
"""
import asyncio
import base64
import json
import os
import time
from urllib.parse import quote

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from websockets.asyncio.client import connect

load_dotenv()
PORT = int(os.environ.get("ASR_MCP_PORT", "8101"))
MODEL = os.environ.get("DEEPGRAM_ASR_MODEL", "nova-3")
# nova-3 "keyterm" boosts recognition of words it would otherwise mishear (the agent's own name).
KEYTERMS = [k.strip() for k in os.environ.get("ASR_KEYTERMS", "Kuya Jukebox,Kuya,Jukebox").split(",") if k.strip()]
URL = (f"wss://api.deepgram.com/v1/listen?model={MODEL}&encoding=linear16&sample_rate=16000&channels=1"
       "&language=en&smart_format=true&interim_results=false&endpointing=false"
       + "".join(f"&keyterm={quote(k)}" for k in KEYTERMS))
mcp = MCPServer("asr-mcp")


def mock() -> bool:
    return os.environ.get("ASR_MOCK") == "1"


class Stream:
    def __init__(self):
        self.ws = None
        self.parts: list[str] = []
        self.final = asyncio.Event()
        self.reader = None
        self.keeper = None

    async def ensure(self):
        if self.ws is not None and self.ws.close_code is None:
            return
        key = os.environ.get("DEEPGRAM_API_KEY")
        if not key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")
        t0 = time.monotonic()
        self.ws = await connect(URL, additional_headers={"Authorization": f"Token {key}"}, max_size=None)
        self.reader = asyncio.create_task(self._read(self.ws))
        if self.keeper is None or self.keeper.done():
            self.keeper = asyncio.create_task(self._keepalive())
        print(f"[asr-mcp] connected to Deepgram in {time.monotonic() - t0:.2f}s", flush=True)

    async def _read(self, ws):
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") == "Results":
                    t = m["channel"]["alternatives"][0]["transcript"]
                    if m.get("is_final") and t:
                        self.parts.append(t)
                    if m.get("from_finalize"):
                        self.final.set()
        except Exception as e:
            print(f"[asr-mcp] reader ended: {type(e).__name__}", flush=True)
        finally:
            self.final.set()  # never leave finish() hanging on a dead socket

    async def _keepalive(self):
        while True:
            await asyncio.sleep(4)
            if self.ws is not None and self.ws.close_code is None:
                try:
                    await self.ws.send(json.dumps({"type": "KeepAlive"}))
                except Exception:
                    pass


S = Stream()


@mcp.tool()
async def asr_start() -> str:
    """Begin a new utterance: clear any old text and make sure the Deepgram connection is warm."""
    S.parts.clear()
    S.final.clear()
    if not mock():
        await S.ensure()
    return "ok"


@mcp.tool()
async def asr_push(audio_b64: str) -> str:
    """Forward one chunk of base64 16-bit mono 16 kHz PCM audio to the live transcription stream."""
    if mock():
        return "ok"
    for attempt in (1, 2):
        try:
            await S.ensure()
            await S.ws.send(base64.b64decode(audio_b64))
            return "ok"
        except Exception as e:
            if attempt == 2:
                raise
            print(f"[asr-mcp] send failed ({type(e).__name__}), reconnecting", flush=True)
            S.ws = None
    return "ok"


@mcp.tool()
async def asr_finish() -> str:
    """End of utterance: flush Deepgram and return the final transcript text."""
    if mock():
        return os.environ.get("ASR_MOCK_TEXT", "this is a mock transcript")
    t0 = time.monotonic()
    await S.ensure()
    S.final.clear()
    await S.ws.send(json.dumps({"type": "Finalize"}))
    try:
        await asyncio.wait_for(S.final.wait(), timeout=3.0)
    except asyncio.TimeoutError:
        print("[asr-mcp] finalize timed out; returning what we have", flush=True)
    text = " ".join(S.parts).strip()
    S.parts.clear()
    print(f"[asr-mcp] finish -> {time.monotonic() - t0:.2f}s: {text!r}", flush=True)
    return text


@mcp.tool()
async def transcribe(audio_b64: str, sample_rate: int = 16000) -> str:
    """Transcribe a whole clip (16 kHz mono PCM16, base64). Convenience wrapper over the streaming tools."""
    await asr_start()
    await asr_push(audio_b64)
    return await asr_finish()


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
