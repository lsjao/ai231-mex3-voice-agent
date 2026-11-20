"""Ducking: lower the music whenever someone is talking (the user, or the agent itself), and restore it afterwards.
Fire-and-forget calls to music-mcp's internal music_duck tool; silently does nothing if music-mcp is not running.

Rules: duck as soon as the user starts speaking or the agent starts speaking; restore when the agent stops speaking,
or ~5 s after the user stopped if the agent never answered (so a cough or a cancelled turn cannot leave it ducked).
"""
import asyncio
import time

from loguru import logger

from src import events
from src.mcp_conn import McpConn

_conn: McpConn | None = None
_last_on: bool | None = None
_bot_speaking = False
_last_bot_stop = 0.0
_restore_task: asyncio.Task | None = None


async def _call(on: bool):
    global _conn, _last_on
    try:
        if _conn is None:
            _conn = McpConn("http://127.0.0.1:8105/mcp")
        state = await _conn.call("music_duck", {"on": on})
        if state == "active" and on != _last_on:           # only a real change while music is actually playing
            events.emit("music", action="duck", title="", on=on)
        _last_on = on
    except Exception as e:     # music server down or not started: music is optional
        logger.debug(f"music_duck({on}) skipped: {type(e).__name__}")
        _conn = None


def _fire(on: bool):
    asyncio.get_running_loop().create_task(_call(on))


def user_started():
    global _restore_task
    if _restore_task is not None:
        _restore_task.cancel()
        _restore_task = None
    _fire(True)


def user_stopped():
    """Restore after a grace period unless the agent starts answering (which keeps it ducked until it finishes)."""
    global _restore_task
    if _restore_task is not None:
        _restore_task.cancel()

    async def later():
        await asyncio.sleep(5.0)
        if not _bot_speaking:
            await _call(False)

    _restore_task = asyncio.get_running_loop().create_task(later())


def bot_started():
    global _bot_speaking
    _bot_speaking = True
    _fire(True)


def bot_stopped():
    global _bot_speaking, _last_bot_stop
    _bot_speaking = False
    _last_bot_stop = time.monotonic()
    _fire(False)


def last_bot_stop() -> float:
    """Monotonic time when the agent last stopped speaking (0.0 if never)."""
    return _last_bot_stop
