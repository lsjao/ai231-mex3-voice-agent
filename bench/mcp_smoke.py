"""Smoke test for asr-mcp + tts-mcp over streamable HTTP, timing what matters on this high-RTT link.
ASR: stream test.wav in 100 ms chunks paced in real time, then time asr_finish() = ASR final after end of speech.
TTS: speak() 3 sentences on a warm connection. Usage: python bench/mcp_smoke.py [wav]"""
import asyncio
import base64
import sys
import time
import wave

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def tool(s, name, args=None):
    r = await s.call_tool(name, args or {})
    if r.is_error:
        raise RuntimeError(r.content)
    return r.content[0].text


async def main():
    w = wave.open(sys.argv[1] if len(sys.argv) > 1 else "test.wav")
    pcm = w.readframes(w.getnframes())
    async with streamable_http_client("http://127.0.0.1:8101/mcp") as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            print("asr tools:", [t.name for t in (await s.list_tools()).tools])
            await tool(s, "asr_start")
            step = 3200  # 100 ms of 16 kHz mono PCM16
            for i in range(0, len(pcm), step):
                await tool(s, "asr_push", {"audio_b64": base64.b64encode(pcm[i:i + step]).decode()})
                await asyncio.sleep(0.1)
            t0 = time.monotonic()
            text = await tool(s, "asr_finish")
            print(f"ASR final {time.monotonic() - t0:.2f}s after last chunk: {text!r}")
    async with streamable_http_client("http://127.0.0.1:8102/mcp") as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            print("tts tools:", [t.name for t in (await s.list_tools()).tools])
            import json
            for sent in ["Hello from the Pi.", "It is sunny in Manila today.", "Anything else I can help with?"]:
                t0 = time.monotonic()
                r = json.loads(await tool(s, "speak_start", {"text": sent}))
                ttfb = time.monotonic() - t0
                n, total = 1, len(base64.b64decode(r["audio"]))
                while not r["done"]:
                    r = json.loads(await tool(s, "speak_next", {"job_id": r["id"]}))
                    total += len(base64.b64decode(r["audio"]))
                    n += 1
                print(f"TTS first chunk {ttfb:.2f}s, all {time.monotonic() - t0:.2f}s, {n} chunks, "
                      f"{total / 2 / 24000:.1f}s audio: {sent!r}")

asyncio.run(main())
