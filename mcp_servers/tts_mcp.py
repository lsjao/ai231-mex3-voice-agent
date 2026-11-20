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

# --- chunked playback: speak_start returns the FIRST audio chunk as soon as Deepgram makes it (~0.3 s) ----------
_jobs: dict[str, asyncio.Queue] = {}
_gen = 0  # bumped by speak_cancel: jobs created earlier give up instead of speaking


async def _run_job(job_id: str, text: str, q: asyncio.Queue, gen: int):
    try:
        async with V.lock:
            if gen != _gen:
                return
            for attempt in (1, 2):
                try:
                    await V.ensure()
                    await V.ws.send(json.dumps({"type": "Speak", "text": text}))
                    await V.ws.send(json.dumps({"type": "Flush"}))
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    V.ws = None
            t0, first = time.monotonic(), True
            while True:
                msg = await asyncio.wait_for(V.ws.recv(), timeout=10)
                if isinstance(msg, bytes):
                    if first:
                        print(f"[tts-mcp] job {job_id}: first audio {time.monotonic() - t0:.2f}s", flush=True)
                        first = False
                    q.put_nowait(msg)
                else:
                    m = json.loads(msg)
                    if m.get("type") in ("Flushed", "Cleared"):
                        break
                    if m.get("type") == "Error":
                        raise RuntimeError(str(m)[:200])
    except Exception as e:
        V.ws = None
        q.put_nowait(e)
    finally:
        q.put_nowait(None)  # end-of-stream marker


async def _drain(q: asyncio.Queue, job_id: str) -> dict:
    """Wait for at least one item, then take everything already queued. Returns {audio_b64, done}."""
    item = await q.get()
    chunks, done = bytearray(), False
    while True:
        if item is None:
            done = True
        elif isinstance(item, Exception):
            _jobs.pop(job_id, None)
            raise item
        else:
            chunks += item
        if done or q.empty():
            break
        item = q.get_nowait()
    if done:
        _jobs.pop(job_id, None)
    return {"audio": base64.b64encode(bytes(chunks)).decode(), "done": done}


@mcp.tool()
async def speak_start(text: str) -> str:
    """Start synthesizing one sentence. Returns JSON {id, audio, done}: audio is base64 PCM16 24 kHz mono holding the
    FIRST chunk; keep calling speak_next(id) until done is true."""
    job_id = str(time.monotonic_ns())
    if os.environ.get("TTS_MOCK") == "1":
        return json.dumps({"id": job_id, "audio": await speak(text), "done": True})
    q: asyncio.Queue = asyncio.Queue()
    _jobs[job_id] = q
    asyncio.create_task(_run_job(job_id, text, q, _gen))
    first = await _drain(q, job_id)
    first["id"] = job_id
    return json.dumps(first)


@mcp.tool()
async def speak_next(job_id: str) -> str:
    """Next chunk of a speak_start job: JSON {audio, done}. Returns done=true with empty audio if the job is gone."""
    if job_id not in _jobs:
        return json.dumps({"audio": "", "done": True})
    return json.dumps(await _drain(_jobs[job_id], job_id))


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
    """Barge-in: drop any audio Deepgram is still producing and any sentences still waiting their turn."""
    global _gen
    _gen += 1
    if V.ws is not None and V.ws.close_code is None:
        try:
            await V.ws.send(json.dumps({"type": "Clear"}))
        except Exception:
            pass
    return "ok"


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
