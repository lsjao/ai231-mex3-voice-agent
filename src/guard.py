"""TurnGuard: sits in front of the LLM and does two jobs, both from the course's context-engineering list.

1. Context budget: keep the system prompt + the last MAX_MESSAGES messages (never starting mid tool-exchange).
   The stable prefix (system prompt, tool schemas) is never edited, so provider-side prefix caching still works.
2. Slow-API recovery: if no reply audio has started SLOW_AFTER seconds after the LLM request (longer after a tool
   result), speak one short line instead of leaving dead air. It stays quiet if the bot is already talking.
"""
import os
import time

from loguru import logger

from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame, InterruptionFrame,
                                   LLMContextFrame, TTSSpeakFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from src import events, music_duck

MAX_MESSAGES = int(os.environ.get("CONTEXT_MAX_MESSAGES", "16"))
SLOW_AFTER = float(os.environ.get("SLOW_AFTER_S", "3.0"))
SLOW_AFTER_TOOL = float(os.environ.get("SLOW_AFTER_TOOL_S", "5.0"))
SLOW_LINE = os.environ.get("SLOW_LINE", "Sorry, the connection is a bit slow. Still working on it.")


def _role(m):
    return m.get("role") if isinstance(m, dict) else getattr(m, "role", None)


def trim_messages(msgs: list, max_messages: int = MAX_MESSAGES) -> list:
    """Keep leading system message(s) + the last max_messages others, starting on a user message."""
    n_sys = 0
    while n_sys < len(msgs) and _role(msgs[n_sys]) in ("system", "developer"):
        n_sys += 1
    system, rest = list(msgs[:n_sys]), list(msgs[n_sys:])
    if len(rest) <= max_messages:
        return msgs if isinstance(msgs, list) else system + rest
    rest = rest[-max_messages:]
    while rest and _role(rest[0]) != "user":   # never open with an orphaned tool result / assistant tool call
        rest = rest[1:]
    return system + rest


class TurnGuard(FrameProcessor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._timer = None
        self._speaking = False

    async def _disarm(self):
        if self._timer is not None:
            await self.cancel_task(self._timer)
            self._timer = None

    async def _fire(self, delay: float):
        import asyncio
        await asyncio.sleep(delay)
        if not self._speaking:
            logger.info(f"[guard] no reply audio after {delay:.1f}s: speaking the slow-connection line")
            events.emit("guard", line=SLOW_LINE)
            await self.push_frame(TTSSpeakFrame(SLOW_LINE, append_to_context=False))

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            ctx = frame.context
            before = len(ctx.messages)
            if before > MAX_MESSAGES + 1:
                ctx.set_messages(trim_messages(ctx.messages))
                logger.info(f"[guard] context trimmed {before} -> {len(ctx.messages)} messages")
            last_is_tool = bool(ctx.messages) and _role(ctx.messages[-1]) == "tool"
            await self._disarm()
            self._timer = self.create_task(self._fire(SLOW_AFTER_TOOL if last_is_tool else SLOW_AFTER),
                                           name="slow_api_guard")
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._speaking = True
            music_duck.bot_started()      # lower the music while the agent talks
            await self._disarm()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._speaking = False
            music_duck.bot_stopped()
        elif isinstance(frame, InterruptionFrame):
            await self._disarm()
        await self.push_frame(frame, direction)
