"""Synthesize a few sentences with OUR tts-mcp (the real agent voice) into a 24 kHz mono wav, for echo measurements.
Usage: python bench/tts_sample.py [out.wav]"""
import asyncio
import base64
import json
import sys
import wave

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

TEXT = ["I looked that up for you.", "The latest result shows a clear winner, and the margin was fairly wide.",
        "Let me know if you want more detail about any of it."]


async def main():
    pcm = bytearray()
    async with streamable_http_client("http://127.0.0.1:8102/mcp") as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            for sent in TEXT:
                r = json.loads((await s.call_tool("speak_start", {"text": sent})).content[0].text)
                jid = r["id"]
                pcm += base64.b64decode(r["audio"])
                while not r["done"]:
                    r = json.loads((await s.call_tool("speak_next", {"job_id": jid})).content[0].text)
                    pcm += base64.b64decode(r["audio"])
    out = sys.argv[1] if len(sys.argv) > 1 else "tts_sample.wav"
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(bytes(pcm))
    print(f"wrote {out}: {len(pcm) / 2 / 24000:.1f}s")

asyncio.run(main())
