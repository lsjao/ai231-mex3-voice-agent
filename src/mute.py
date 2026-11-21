"""User mute strategy for tool calls: mute the mic only while the spoken holding phrase plays, then listen again.

Why: the stock FunctionCallUserMuteStrategy mutes the user for the whole tool call. That was fine when tools took ~3 s, but a
search turn takes 6-20 s, and during that silence the user could not interrupt or cancel at all, which felt like broken
barge-in. The only real risk is the holding phrase's own echo, which lasts about two seconds, so we mute just that window.
"""
import time

from pipecat.frames.frames import Frame, FunctionCallCancelFrame, FunctionCallResultFrame, FunctionCallsStartedFrame
from pipecat.turns.user_mute.base_user_mute_strategy import BaseUserMuteStrategy


class HoldPhraseMuteStrategy(BaseUserMuteStrategy):
    def __init__(self, mute_secs: float = 2.2):
        super().__init__()
        self._mute_secs = mute_secs
        self._started: dict[str, float] = {}

    async def process_frame(self, frame: Frame) -> bool:
        await super().process_frame(frame)
        if isinstance(frame, FunctionCallsStartedFrame):
            for f in frame.function_calls:
                self._started[f.tool_call_id] = time.monotonic()
        elif isinstance(frame, (FunctionCallCancelFrame, FunctionCallResultFrame)):
            self._started.pop(frame.tool_call_id, None)
        now = time.monotonic()
        return any(now - t < self._mute_secs for t in self._started.values())
