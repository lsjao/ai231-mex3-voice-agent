"""Events server for the live visual (port 8106, all interfaces, CORS open).

  GET /events                      Server-Sent Events: the CURRENT agent session's real events as `data: {...}`
  GET /sessions                    JSON list of recorded sessions (newest first)
  GET /replay?session=<id>         that session's events as a JSON array
  GET /health                      {"ok": true}

It only serves what src/events.py wrote to ~/mex3/logs/sessions/*.jsonl. It never generates events. There is no
authentication: it exposes conversation transcripts to anyone on the same network, so use it on your own hotspot.
Set EVENTS_HOST=127.0.0.1 to keep it local.
"""
import asyncio
import json
import os
import re
import time
from pathlib import Path

from aiohttp import web

DIR = Path(os.environ.get("EVENTS_DIR", str(Path.home() / "mex3" / "logs" / "sessions")))
PORT = int(os.environ.get("EVENTS_PORT", "8106"))
HOST = os.environ.get("EVENTS_HOST", "0.0.0.0")
LIVE_WINDOW_S = 120          # a session whose file was written within this window counts as the live one
ID_RX = re.compile(r"^\d{8}-\d{6}$")
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*", "Cache-Control": "no-store"}


@web.middleware
async def cors(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS)
    resp = await handler(request)
    if not isinstance(resp, web.StreamResponse) or not resp.prepared:
        resp.headers.update(CORS)
    return resp


def agent_running() -> bool:
    """True while the voice agent process (python -m src.agent) is alive on this Pi. A quiet agent writes no events, so
    file age alone cannot tell 'idle but running' from 'stopped'."""
    for p in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            c = p.read_bytes().replace(b"\x00", b" ")
        except OSError:
            continue
        if b"-m src.agent" in c and b"events_server" not in c and b"bash -c" not in c:
            return True
    return False


def session_files() -> list[Path]:
    return sorted(DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if DIR.exists() else []


def read_events(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue      # a half-written last line while the agent is mid-write
    return out


async def health(_):
    return web.json_response({"ok": True, "sessions": len(session_files())})


async def sessions(_):
    rows = []
    now = time.time()
    files = session_files()
    running = agent_running()
    for p in files:
        ev = read_events(p)
        if not ev:
            continue
        users = [e for e in ev if e["type"] == "user"]
        rows.append({"id": p.stem, "started": ev[0].get("wall"), "events": len(ev), "turns": len(users),
                     "duration_s": round(ev[-1]["t"] - ev[0]["t"], 1), "live": now - p.stat().st_mtime < LIVE_WINDOW_S or (running and p == files[0])})
    return web.json_response(rows)


async def replay(request):
    sid = request.query.get("session", "")
    path = DIR / f"{sid}.jsonl"
    if not ID_RX.match(sid) or not path.exists():
        return web.json_response({"error": "unknown session"}, status=404)
    return web.json_response(read_events(path))


async def events(request):
    resp = web.StreamResponse(headers={**CORS, "Content-Type": "text/event-stream", "Connection": "keep-alive",
                                       "X-Accel-Buffering": "no"})
    await resp.prepare(request)
    await resp.write(b"retry: 2000\n\n")
    current: Path | None = None
    offset = 0
    last_ping = time.monotonic()
    try:
        while True:
            files = session_files()
            newest = files[0] if files else None
            if newest is not None and newest != current:
                current = newest
                # Backlog only if this session is live now; an old finished session is not "live".
                live = time.time() - newest.stat().st_mtime < LIVE_WINDOW_S or agent_running()
                offset = 0 if live else newest.stat().st_size
            if current is not None and current.exists():
                size = current.stat().st_size
                if size > offset:
                    with open(current, "rb") as f:
                        f.seek(offset)
                        chunk = f.read(size - offset)
                    cut = chunk.rfind(b"\n") + 1            # only whole lines; keep a partial last line for next time
                    for line in chunk[:cut].splitlines():
                        if line.strip():
                            await resp.write(b"data: " + line + b"\n\n")
                    offset += cut
            if time.monotonic() - last_ping > 15:
                await resp.write(b": ping\n\n")
                last_ping = time.monotonic()
            await asyncio.sleep(0.1)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    app = web.Application(middlewares=[cors])
    app.add_routes([web.get("/health", health), web.get("/sessions", sessions), web.get("/replay", replay),
                    web.get("/events", events)])
    print(f"[events] serving {DIR} on http://{HOST}:{PORT}", flush=True)
    web.run_app(app, host=HOST, port=PORT, print=None)


if __name__ == "__main__":
    main()
