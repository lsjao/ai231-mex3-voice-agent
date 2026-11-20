"""Echo filter: the agent's own voice can leak back into the mic (no acoustic echo cancellation on this Pi), get
transcribed as if the user said it, and make the agent answer itself. We remember what the agent said recently and drop
any 'user' transcript that is just a fragment of it.

Deliberately conservative: it only drops multi-word fragments, so a short genuine reply like 'Tokyo' or 'stop'
(which may also appear in the agent's last sentence) is never discarded.
"""
import re
import time
from collections import deque

WINDOW_S = 20.0     # how long a spoken sentence stays 'recent'
MIN_WORDS = 2       # shorter transcripts are never treated as echo
_recent: deque = deque(maxlen=16)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("’", "'")).split())


def note_bot_text(text: str) -> None:
    """Call with every sentence the agent is about to speak."""
    n = _norm(text)
    if n:
        _recent.append((time.monotonic(), n))


def is_echo(transcript: str, now: float | None = None) -> bool:
    """True if the transcript is a multi-word fragment of something the agent said within WINDOW_S seconds."""
    n = _norm(transcript)
    if len(n.split()) < MIN_WORDS:
        return False
    now = now if now is not None else time.monotonic()
    return any(now - ts <= WINDOW_S and n in said for ts, said in _recent)


def reset() -> None:
    _recent.clear()
