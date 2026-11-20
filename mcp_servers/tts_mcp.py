"""tts-mcp: our MCP server wrapping Deepgram Aura-2 text-to-speech. Runs on the Pi, streamable HTTP on localhost.

Keeps ONE warm Deepgram WebSocket (no TLS handshake per sentence; the Pi is ~240 ms RTT from Deepgram).
Tools:
  speak(text) -> base64 PCM16 mono at TTS_SAMPLE_RATE (24000). Call once per sentence.
  speak_cancel()  barge-in: tell Deepgram to drop what it is still synthesizing; the in-flight speak() returns early.
Set TTS_MOCK=1 for a short tone without network or key.
"""
import asyncio
import base64
import json
import math
import os
import struct
import time

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from websockets.asyncio.client import connect

load_dotenv()
PORT = int(os.environ.get("TTS_MCP_PORT", "8102"))
MODEL = os.environ.get("DEEPGRAM_TTS_MODEL", "aura-2-thalia-en")
RATE = int(os.environ.get("TTS_SAMPLE_RATE", "24000"))
URL = f"wss://api.deepgram.com/v1/speak?model={MODEL}&encoding=linear16&sample_rate={RATE}"
mcp = MCPServer("tts-mcp")


class Voice:
    def __init__(self):
        self.ws = None
        self.lock = asyncio.Lock()
        self.keeper = None

    async def ensure(self):
        if self.ws is not None and self.ws.close_code is None:
            return
        key = os.environ.get("DEEPGRAM_API_KEY")
        if not key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")
        t0 = time.monotonic()
        self.ws = await connect(URL, additional_headers={"Authorization": f"Token {key}"}, max_size=None)
        print(f"[tts-mcp] connected to Deepgram in {time.monotonic() - t0:.2f}s", flush=True)
        if self.keeper is None or self.keeper.done():
            self.keeper = asyncio.create_task(self._keepalive())

    async def _keepalive(self):
        while True:  # Deepgram closes an idle socket; a Flush on an empty buffer is harmless
            await asyncio.sleep(20)
            if self.ws is not None and self.ws.close_code is None and not self.lock.locked():
                try:
                    await self.ws.send(json.dumps({"type": "Flush"}))
                except Exception:
                    pass

    async def synth(self, text: str) -> bytes:
        async with self.lock:
            await self.ensure()
            await self.ws.send(json.dumps({"type": "Speak", "text": text}))
            await self.ws.send(json.dumps({"type": "Flush"}))
            audio = bytearray()
            first = None
            t0 = time.monotonic()
            while True:
                msg = await asyncio.wait_for(self.ws.recv(), timeout=10)
                if isinstance(msg, bytes):
                    if first is None:
                        first = time.monotonic() - t0
                    audio += msg
                else:
                    m = json.loads(msg)
                    if m.get("type") in ("Flushed", "Cleared"):
                        break
                    if m.get("type") == "Error":
                        raise RuntimeError(str(m)[:200])
            first_s = "none" if first is None else f"{first:.2f}s"
            print(f"[tts-mcp] {len(text)} chars: first audio {first_s}, total {time.monotonic() - t0:.2f}s, "
                  f"{len(audio) / 2 / RATE:.1f}s of audio", flush=True)
            return bytes(audio)


V = Voice()


@mcp.tool()
async def speak(text: str) -> str:
    """Synthesize one sentence; returns base64 16-bit mono PCM at 24 kHz."""
    if os.environ.get("TTS_MOCK") == "1":
        n = int(RATE * 0.4)
        pcm = b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 440 * i / RATE))) for i in range(n))
        return base64.b64encode(pcm).decode()
    for attempt in (1, 2):
        try:
            return base64.b64encode(await V.synth(text)).decode()
        except Exception as e:
            if attempt == 2:
                raise
            print(f"[tts-mcp] synth failed ({type(e).__name__}), reconnecting", flush=True)
            V.ws = None
    return ""


@mcp.tool()
async def speak_cancel() -> str:
    """Barge-in: drop any audio Deepgram is still producing."""
    if V.ws is not None and V.ws.close_code is None:
        try:
            await V.ws.send(json.dumps({"type": "Clear"}))
        except Exception:
            pass
    return "ok"


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
