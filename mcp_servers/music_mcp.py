"""music-mcp: our MCP server that plays local music through the Pi's speaker (the ME2 'Kuya Jukebox' capability).
Streamable HTTP on localhost:8105. Music files are NOT in the repo (copyrighted): they live in MUSIC_DIR
(default ~/vcm/music, laid out as playlist_<name>/*.mp3 from ME2).

Design (carried over from ME2's player): sounddevice output with a software gain, so volume changes and ducking are
instant and there is no dependency on external players or ALSA mixers. MP3 decode uses libsndfile >= 1.1.

Tools for the LLM: music_play, music_pause, music_resume, music_stop, music_next, music_previous, music_volume, music_status.
Internal (the agent calls it, the LLM does not): music_duck(on) lowers the music while someone is talking.
"""
import asyncio
import glob
import os
import random
import re
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf
from mcp.server.mcpserver import MCPServer

MUSIC_DIR = os.environ.get("MUSIC_DIR", os.path.expanduser("~/vcm/music"))
PORT = int(os.environ.get("MUSIC_MCP_PORT", "8105"))
EXTS = (".mp3", ".wav", ".ogg", ".flac")
DUCK_FACTOR = 0.3    # gain multiplier while someone is talking (the speaker itself runs at 80 % to avoid echo)
mcp = MCPServer("music-mcp")


def find_device() -> int | None:
    for i, d in enumerate(sd.query_devices()):
        if "headphones" in d["name"].lower() and d["max_output_channels"] > 0:
            return i
    return None


def scan() -> dict[str, list[str]]:
    lists = {}
    for d in sorted(glob.glob(os.path.join(MUSIC_DIR, "playlist_*"))):
        files = sorted(f for f in glob.glob(os.path.join(d, "*")) if f.lower().endswith(EXTS))
        if files:
            lists[os.path.basename(d)[len("playlist_"):]] = files
    return lists


def spoken_title(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0].replace(" - ", ", ")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


class Player:
    def __init__(self):
        self.queue: list[str] = []
        self.idx = 0
        self.volume = int(os.environ.get("MUSIC_VOLUME", "65"))   # 0-100
        self.ducked = False
        self.paused = threading.Event()
        self.stop_flag = threading.Event()
        self.skip = 0          # +1 next, -1 previous (set by tools, consumed by the playback thread)
        self.thread: threading.Thread | None = None
        self.device = find_device()

    def gain(self) -> float:
        g = (max(0, min(100, self.volume)) / 100.0) ** 2     # squared: the low end of the range stays usable
        return g * (DUCK_FACTOR if self.ducked else 1.0)

    @property
    def active(self) -> bool:
        return self.thread is not None and self.thread.is_alive() and not self.stop_flag.is_set()

    def halt(self):
        self.stop_flag.set()
        if self.thread is not None and self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
        self.thread = None

    def start(self, files: list[str], start_idx: int = 0):
        self.halt()
        self.queue, self.idx, self.skip = list(files), start_idx % len(files), 0
        self.stop_flag.clear()
        self.paused.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="music")
        self.thread.start()

    def _run(self):
        try:
            while not self.stop_flag.is_set():
                with sf.SoundFile(self.queue[self.idx]) as f:
                    with sd.OutputStream(samplerate=f.samplerate, channels=2, dtype="float32", device=self.device) as out:
                        while not self.stop_flag.is_set() and not self.skip:
                            if self.paused.is_set():
                                out.write(np.zeros((1024, 2), dtype=np.float32))
                                continue
                            data = f.read(2048, dtype="float32", always_2d=True)
                            if len(data) == 0:
                                break
                            data = np.repeat(data, 2, axis=1) if data.shape[1] == 1 else data[:, :2]
                            out.write((data * self.gain()).astype(np.float32))
                if self.stop_flag.is_set():
                    break
                step, self.skip = (self.skip or 1), 0
                self.idx = (self.idx + step) % len(self.queue)
        except Exception as e:   # never take the server down because of one bad file or device hiccup
            print(f"[music-mcp] playback error: {type(e).__name__}: {e}", flush=True)


P = Player()


def status_text() -> str:
    if not P.active:
        return "Nothing is playing."
    state = "Paused on" if P.paused.is_set() else "Playing"
    return f"{state} {spoken_title(P.queue[P.idx])}. Volume {P.volume} percent."


@mcp.tool()
async def music_play(query: str = "") -> str:
    """Play music from the local library. The query can be a playlist name (chill or focus), a song title or an
    artist name; leave it empty for a shuffled mix of everything. Starts playing immediately."""
    lists = scan()
    if not lists:
        return "The music library is empty."
    q = norm(query)
    files: list[str] = []
    start = 0
    if q:
        for name, fl in lists.items():
            if q == norm(name) or norm(name) in q.split():
                files = list(fl)
                random.shuffle(files)
                break
        if not files:
            every = [f for fl in lists.values() for f in fl]
            hits = [f for f in every if q in norm(os.path.basename(f)) or
                    all(w in norm(os.path.basename(f)) for w in q.split())]
            if hits:
                files = hits + [f for f in every if f not in hits]
    else:
        files = [f for fl in lists.values() for f in fl]
        random.shuffle(files)
    if not files:
        return f"I could not find {query} in the library. I have these playlists: {', '.join(lists)}."
    await asyncio.to_thread(P.start, files, start)
    return f"Playing {spoken_title(files[0])}."


@mcp.tool()
async def music_pause() -> str:
    """Pause the music."""
    if not P.active:
        return "Nothing is playing."
    P.paused.set()
    return "Paused."


@mcp.tool()
async def music_resume() -> str:
    """Resume paused music."""
    if not P.active:
        return "Nothing is playing. Ask me to play something."
    P.paused.clear()
    return f"Resuming {spoken_title(P.queue[P.idx])}."


@mcp.tool()
async def music_stop() -> str:
    """Stop the music completely."""
    if not P.active:
        return "Nothing is playing."
    await asyncio.to_thread(P.halt)
    return "Stopped."


@mcp.tool()
async def music_next() -> str:
    """Skip to the next song."""
    if not P.active:
        return "Nothing is playing."
    P.skip, _ = 1, P.paused.clear()
    return "Next song."


@mcp.tool()
async def music_previous() -> str:
    """Go back to the previous song."""
    if not P.active:
        return "Nothing is playing."
    P.skip, _ = -1, P.paused.clear()
    return "Previous song."


@mcp.tool()
async def music_volume(level: int) -> str:
    """Set the music volume from 0 to 100 percent."""
    P.volume = max(0, min(100, int(level)))
    return f"Music volume set to {P.volume} percent."


@mcp.tool()
async def music_adjust(delta: int) -> str:
    """Internal: raise or lower the music volume by delta percentage points (used by the fast voice-command path)."""
    if not P.active:
        return "Nothing is playing."
    P.volume = max(0, min(100, P.volume + int(delta)))
    return f"Volume {P.volume} percent."


@mcp.tool()
async def music_status() -> str:
    """Say what is playing right now."""
    return status_text()


@mcp.tool()
async def music_duck(on: bool) -> str:
    """Internal: lower the music while someone is talking (called by the agent, not by the LLM)."""
    P.ducked = bool(on)
    return "ok"


if __name__ == "__main__":
    print(f"[music-mcp] library: { {k: len(v) for k, v in scan().items()} } device={P.device}", flush=True)
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
