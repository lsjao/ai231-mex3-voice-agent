"""Real-event log for the live visual. Every event is appended as one JSON line to ~/mex3/logs/sessions/<session>.jsonl
(one file per agent run). scripts/events_server.py streams and replays these files over HTTP on port 8106.

HARD RULE: events are emitted ONLY from things that really happened in the pipeline (a transcript arrived, the model
spoke, a tool ran, the user interrupted...). Nothing here is scripted or generated. Disabled in benchmark mode (BENCH=1)
so the class benchmark's injected test phrases never show up as conversations.

Event shapes (all carry t = Pi monotonic seconds, wall = epoch seconds, session, turn):
  {"type":"state","state":"idle|listening|thinking|speaking|tool|music"}
  {"type":"user","text":"...","asr_ms":N}                      # final transcript; opens a new turn (turn += 1)
  {"type":"agent","text":"...","llm_ms":N,"tts_ms":N,"e2e_ms":N}
  {"type":"tool","name":"get_weather","phase":"start|end","ms":N}
  {"type":"interrupt"}  {"type":"guard","line":"..."}  {"type":"echo_dropped","text":"..."}
  {"type":"music","action":"play|pause|stop|duck","title":"...","on":true|false}   # 'on' only for duck
Turn numbering: the user's final transcript opens turn n; every event after it (agent, tool, music...) until the next
user transcript carries turn n. Events before the first transcript carry turn 0.
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

ENABLED = os.environ.get("BENCH") != "1"
DIR = Path(os.environ.get("EVENTS_DIR", str(Path.home() / "mex3" / "logs" / "sessions")))

_lock = threading.Lock()
_session: str | None = None
_turn = 0
_fh = None
music_active = False       # kept up to date from music events, used to settle the state after the agent stops talking


def session_id() -> str:
    global _session
    if _session is None:
        _session = datetime.now().strftime("%Y%m%d-%H%M%S")
    return _session


def new_session() -> str:
    """Start a fresh session file (called once when the agent starts)."""
    global _session, _turn, _fh, music_active
    with _lock:
        if _fh is not None:
            try:
                _fh.close()
            except Exception:
                pass
        _fh, _turn, music_active = None, 0, False
        _session = datetime.now().strftime("%Y%m%d-%H%M%S")
    return _session


def emit(type_: str, **fields) -> None:
    """Append one real event. Never raises: logging must not be able to break the conversation."""
    global _turn, _fh, music_active
    if not ENABLED:
        return
    try:
        if type_ == "user":
            _turn += 1
        if type_ == "music":
            if fields.get("action") == "play":
                music_active = True
            elif fields.get("action") in ("stop", "pause"):
                music_active = False
        ev = {"type": type_, "t": round(time.monotonic(), 3), "wall": round(time.time(), 3),
              "session": session_id(), "turn": _turn, **fields}
        line = json.dumps(ev, ensure_ascii=False)
        with _lock:
            if _fh is None:
                DIR.mkdir(parents=True, exist_ok=True)
                _fh = open(DIR / f"{session_id()}.jsonl", "a", encoding="utf-8", buffering=1)
            _fh.write(line + "\n")
            _fh.flush()
    except Exception:
        pass


def settle() -> None:
    """After the agent finished talking (or a turn ended with no reply), go back to music or idle."""
    emit("state", state="music" if music_active else "idle")
