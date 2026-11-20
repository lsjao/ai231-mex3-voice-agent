"""Fast path for spoken music commands: no LLM in the loop, so 'stop the music' takes effect ~0.4 s after the user stops
talking (ASR final + one local MCP call) instead of 2-4 s. Anything that is not clearly a music command returns False
and goes to the LLM as usual, so conversation is unaffected.

A bare 'stop' is only treated as 'stop the music' when music is actually playing AND the agent has not just been talking
(otherwise it is a barge-in aimed at the agent's own speech, which the VAD already handled).
"""
import re
import time

from loguru import logger

from src import music_duck
from src.mcp_conn import McpConn

_conn: McpConn | None = None
_W = r"(?:the |this |that |my |some |a )?"
_NOUN = r"(?:music|song|songs|track|tracks|playlist|tune|tunes|playing)"

STOP = re.compile(rf"\b(?:stop|turn off|shut off|switch off|kill|end|cut)\b.{{0,22}}\b{_NOUN}\b|\b{_NOUN}\b.{{0,14}}\b(?:off|stop)\b", re.I)
PAUSE = re.compile(rf"\bpause\b.{{0,18}}\b{_NOUN}\b|\bpause\b\s*(?:it|please|the)?\s*$", re.I)
RESUME = re.compile(rf"\b(?:resume|unpause|continue|keep playing|play again)\b.{{0,18}}(?:{_NOUN}|it)?|\bresume\b", re.I)
NEXT = re.compile(r"\b(?:next (?:song|track|one)|skip (?:this |the |that )?(?:song|track|one)?|play (?:the )?next)\b", re.I)
PREV = re.compile(r"\b(?:previous (?:song|track|one)|go back (?:a |one )?(?:song|track)?|last song|play (?:the )?previous)\b", re.I)
LOUDER = re.compile(r"\b(?:turn (?:it |the music |the volume )?up|louder|volume up|increase the volume|raise the volume|more volume)\b", re.I)
QUIETER = re.compile(r"\b(?:turn (?:it |the music |the volume )?down|quieter|softer|volume down|lower the volume|decrease the volume|too loud)\b", re.I)
BARE_STOP = re.compile(r"^\W*(?:okay\W+|ok\W+|please\W+)?(?:stop|pause|quiet|silence|enough)(?:\W+(?:it|that|please|now))?\W*$", re.I)


async def _call(tool: str, args: dict | None = None) -> str:
    global _conn
    if _conn is None:
        _conn = McpConn("http://127.0.0.1:8105/mcp")
    return await _conn.call(tool, args or {})


async def _music_active() -> bool:
    return "nothing is playing" not in (await _call("music_status")).lower()


async def handle(text: str, say) -> bool:
    """Return True if `text` was a music command that we executed (and spoke a short confirmation through `say`)."""
    t0 = time.monotonic()
    try:
        action = None
        if STOP.search(text):
            action = ("music_stop", {}, "Stopped.")
        elif PAUSE.search(text):
            action = ("music_pause", {}, "Paused.")
        elif NEXT.search(text):
            action = ("music_next", {}, "Next song.")
        elif PREV.search(text):
            action = ("music_previous", {}, "Previous song.")
        elif QUIETER.search(text):
            action = ("music_adjust", {"delta": -15}, "Quieter.")
        elif LOUDER.search(text):
            action = ("music_adjust", {"delta": 15}, "Louder.")
        elif RESUME.search(text) and re.search(rf"\b{_NOUN}\b|\bresume\b|\bunpause\b|\bit\b", text, re.I):
            action = ("music_resume", {}, "Resuming.")
        elif BARE_STOP.match(text):
            if time.monotonic() - music_duck.last_bot_stop() < 2.0:
                return False                      # the user was most likely interrupting the agent, not the music
            if not await _music_active():
                return False
            action = ("music_stop", {}, "Stopped.")
        if action is None:
            return False
        tool, args, reply = action
        if tool != "music_stop" and tool != "music_adjust" and not await _music_active():
            return False                          # nothing playing: let the LLM answer ("nothing is playing")
        result = await _call(tool, args)
        logger.info(f"[fast] {text!r} -> {tool}{args or ''} in {time.monotonic() - t0:.2f}s ({result})")
        if tool in ("music_stop", "music_adjust") and "nothing is playing" in result.lower():
            return False
        await say(reply)
        return True
    except Exception as e:                        # music server down etc.: fall back to the LLM path
        logger.warning(f"[fast] command path failed ({type(e).__name__}); falling back to the LLM")
        return False
