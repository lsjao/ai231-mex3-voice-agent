"""Speak one line through OUR tts-mcp and play it on the Pi's speaker (a spoken 'ready' instead of the ringtone).
Usage: python bench/say.py "Ready when you are."   (tts-mcp must be up: bash scripts/start_servers.sh)"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import wave

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    text = " ".join(sys.argv[1:]) or "Ready."
    pcm = bytearray()
    async with streamable_http_client("http://127.0.0.1:8102/mcp") as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            r = json.loads((await s.call_tool("speak_start", {"text": text})).content[0].text)
            jid = r["id"]
            pcm += base64.b64decode(r["audio"])
            while not r["done"]:
                r = json.loads((await s.call_tool("speak_next", {"job_id": jid})).content[0].text)
                pcm += base64.b64decode(r["audio"])
    path = os.path.join(tempfile.gettempdir(), "say.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(bytes(pcm))
    subprocess.run(["aplay", "-q", "-D", "plughw:Headphones", path], check=False)

asyncio.run(main())
