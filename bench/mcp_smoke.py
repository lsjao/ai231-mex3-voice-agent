"""Smoke test: connect to asr-mcp and tts-mcp over streamable HTTP, list tools, call each once, print latency.
Usage: python bench/mcp_smoke.py [wav]   (wav: 16 kHz mono, default test.wav)"""
import asyncio, base64, sys, time, wave
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def call(url, tool, args):
    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            t0 = time.monotonic()
            res = await s.call_tool(tool, args)
            dt = time.monotonic() - t0
            if res.isError:
                raise RuntimeError(res.content)
            return names, res.content[0].text, dt


async def main():
    w = wave.open(sys.argv[1] if len(sys.argv) > 1 else "test.wav")
    pcm = w.readframes(w.getnframes())
    names, text, dt = await call("http://127.0.0.1:8101/mcp", "transcribe",
                                 {"audio_b64": base64.b64encode(pcm).decode(), "sample_rate": 16000})
    print(f"asr-mcp tools={names} transcribe={dt:.2f}s text={text!r}")
    names, b64, dt = await call("http://127.0.0.1:8102/mcp", "speak", {"text": "Hello from the Pi.", "sample_rate": 24000})
    print(f"tts-mcp tools={names} speak={dt:.2f}s audio={len(base64.b64decode(b64))/2/24000:.2f}s")

asyncio.run(main())
