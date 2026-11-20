"""TraceObserver: logs each conversational turn with timings, so we can see what was heard, what the LLM said,
and how long each stage took (all on one monotonic clock). Reads standard Pipecat frames only."""
import time

from loguru import logger

from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame, InterruptionFrame,
                                   LLMFullResponseEndFrame, LLMTextFrame, TranscriptionFrame,
                                   VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.observers.base_observer import BaseObserver, FramePushed


class TraceObserver(BaseObserver):
    def __init__(self):
        super().__init__()
        self._last: dict[str, float] = {}
        self._text: list[str] = []
        self._t_vad_stop = self._t_final = None
        self._llm_first = False

    def _once(self, frame) -> bool:
        # Pipecat broadcasts some frames as two copies with different ids: de-duplicate by type within 50 ms.
        key, now = type(frame).__name__, time.monotonic()
        if now - self._last.get(key, -1.0) < 0.05:
            return False
        self._last[key] = now
        return True

    @staticmethod
    def _since(t0) -> str:
        return "n/a" if t0 is None else f"{time.monotonic() - t0:.2f}s"

    async def on_push_frame(self, data: FramePushed):
        f, now = data.frame, time.monotonic()
        if isinstance(f, VADUserStartedSpeakingFrame) and self._once(f):
            logger.info("[trace] user speech start")
        elif isinstance(f, VADUserStoppedSpeakingFrame) and self._once(f):
            self._t_vad_stop, self._t_final, self._llm_first = now, None, True
            logger.info("[trace] user speech end (VAD)")
        elif isinstance(f, TranscriptionFrame) and self._once(f):
            self._t_final = now
            logger.info(f"[trace] ASR final +{self._since(self._t_vad_stop)} after VAD end: {f.text!r}")
        elif isinstance(f, LLMTextFrame) and self._once(f):
            if self._llm_first:
                self._llm_first = False
                logger.info(f"[trace] LLM first token +{self._since(self._t_final)} after ASR final")
            self._text.append(f.text)
        elif isinstance(f, LLMFullResponseEndFrame) and self._once(f):
            logger.info(f"[trace] bot said: {''.join(self._text).strip()!r}")
            self._text = []
        elif isinstance(f, BotStartedSpeakingFrame) and self._once(f):
            logger.info(f"[trace] bot audio started: E2E {self._since(self._t_vad_stop)} after VAD end")
        elif isinstance(f, BotStoppedSpeakingFrame) and self._once(f):
            logger.info("[trace] bot audio stopped")
        elif isinstance(f, InterruptionFrame) and self._once(f):
            logger.info("[trace] INTERRUPTION (barge-in)")
